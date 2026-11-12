/** FTC/FRC telemetry checks mirrored from core/ftc_frc.py for web/Node clients. */
export const FTC_DEFAULT_LIMITS = Object.freeze({
  motor_power: [-1, 1],
  battery_voltage: [10.5, 14.5],
  battery_sag_voltage: 12,
  sag_min_total_power: 2,
  velocity_tolerance: 50,
  min_moving_speed: 50,
  max_speed: 100,
  heading_jump_deg: 90,
});

export const FTC_PROFILE = Object.freeze({
  schema_version: 1,
  name: "FTC / FRC (school robotics)",
  robotics_profile: "ftc",
  robotics_limits: Object.freeze({}),
  ftc_limits: FTC_DEFAULT_LIMITS,
  conditions: Object.freeze({}),
});

export function resolveFtcProfile(name) {
  const key = String(name || "").trim().toLowerCase();
  return key === "ftc" || key === "frc" ? structuredClone(FTC_PROFILE) : null;
}

function normalizedName(value) {
  return String(value)
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

const COLUMN_ALIASES = new Map([
  ["battery_v", "battery_voltage"],
  ["voltage_v", "voltage"],
  ["battery", "battery_voltage"],
  ["heading", "heading_deg"],
  ["gyro_heading", "heading_deg"],
  ["imu_heading", "heading_deg"],
  ["imu_yaw", "heading_deg"],
  ["yaw_deg", "heading_deg"],
  ["odometry_x", "x"],
  ["odometry_y", "y"],
  ["x_position", "x"],
  ["y_position", "y"],
]);

export function normalizeFtcRows(rows) {
  return rows.map((row) => {
    const out = {};
    for (const [rawKey, value] of Object.entries(row)) {
      let key = normalizedName(rawKey);
      key = COLUMN_ALIASES.get(key) ?? key;
      if (key.endsWith("_encoder_ticks")) key = `${key.slice(0, -"_encoder_ticks".length)}_encoder`;
      if (key === "motor_power") key = "power";
      out[key] = value;
    }
    return out;
  });
}

function number(value) {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

const firstPresent = (rows, keys) => keys.find((key) => rows.some((row) => key in row));
const median = (values) => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};

/** Validate rows without truncation; return the same semantic report as Python core. */
export function validateFtcLog(inputRows, limitOverrides = {}) {
  const rows = normalizeFtcRows(inputRows);
  const limits = { ...FTC_DEFAULT_LIMITS, ...limitOverrides };
  const [powerLow, powerHigh] = limits.motor_power;
  const [voltageLow, voltageHigh] = limits.battery_voltage;
  const failed = new Map();
  const warnings = new Map();
  const excluded = new Map();
  const fail = (check, index, detail, reason) => {
    if (!failed.has(check)) failed.set(check, []);
    failed.get(check).push(detail);
    if (!excluded.has(index)) excluded.set(index, []);
    excluded.get(index).push(reason);
  };
  if (!rows.length) {
    return { verdict: "passed", failed_checks: [], warnings: [], excluded_rows: {}, episodes: [], summary: { rows: 0 } };
  }
  const timeKey = firstPresent(rows, ["time", "t", "timestamp", "elapsed_time"]) ?? "time";
  const episodeKey = firstPresent(rows, ["episode_id", "episode", "match", "segment"]);
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))].sort();
  const powerColumns = columns.filter((column) => column.endsWith("_power") || column === "power");
  const headingColumns = columns.filter((column) => column === "heading_deg" || column.endsWith("_heading_deg"));
  const voltageColumn = columns.find((column) => column.includes("battery") || column === "voltage");
  const groupOf = (row) => String((episodeKey ? row[episodeKey] : "log") ?? "log");

  for (let index = 0; index < rows.length; index++) {
    const row = rows[index];
    for (const column of powerColumns) {
      const value = number(row[column]);
      if (value !== null && !(powerLow <= value && value <= powerHigh)) {
        fail("power_range", index, `row ${index}: ${column}=${value} outside [${powerLow}, ${powerHigh}]`, `${column}=${value} outside [${powerLow}, ${powerHigh}]`);
      }
    }
    if (voltageColumn) {
      const value = number(row[voltageColumn]);
      if (value !== null && !(voltageLow <= value && value <= voltageHigh)) {
        if (!warnings.has("battery_voltage_range")) warnings.set("battery_voltage_range", []);
        warnings.get("battery_voltage_range").push(`row ${index}: ${voltageColumn}=${value} outside warn band [${voltageLow}, ${voltageHigh}]`);
      }
    }
  }

  for (let index = 1; index < rows.length; index++) {
    const previous = rows[index - 1], row = rows[index];
    if (groupOf(previous) !== groupOf(row)) continue;
    const t0 = number(previous[timeKey]), t1 = number(row[timeKey]);
    if (t0 === null || t1 === null) continue;
    const dt = t1 - t0;
    if (dt <= 0) {
      fail("time_order", index, `row ${index}: time did not increase (${t0} -> ${t1})`, "time did not increase");
      continue;
    }
    const totalPower = powerColumns.reduce((sum, column) => sum + Math.abs(number(row[column]) ?? 0), 0);
    if (voltageColumn) {
      const voltage = number(row[voltageColumn]);
      if (voltage !== null && voltage < limits.battery_sag_voltage && totalPower >= limits.sag_min_total_power) {
        fail("battery_sag", index, `row ${index}: battery ${voltage}V below ${limits.battery_sag_voltage}V while total |power| is ${totalPower}`, `battery sag: ${voltage}V under load ${totalPower}`);
      }
    }
    for (const column of columns) {
      if (!(column.endsWith("_position") || column.endsWith("_encoder"))) continue;
      const p0 = number(previous[column]), p1 = number(row[column]);
      if (p0 === null || p1 === null) continue;
      const derived = (p1 - p0) / dt;
      const velocityColumn = column.endsWith("_position") ? `${column.slice(0, -"position".length)}velocity` : null;
      const reported = velocityColumn ? number(row[velocityColumn]) : null;
      if (reported !== null && Math.abs(derived - reported) > limits.velocity_tolerance) {
        fail("encoder_velocity", index, `row ${index}: ${column} implies ${derived}/s but ${velocityColumn} says ${reported}/s`, `encoder-derived velocity ${derived}/s disagrees with reported ${reported}/s`);
      }
      if (Math.abs(derived) > limits.min_moving_speed && powerColumns.length && powerColumns.every((power) => Math.abs(number(row[power]) ?? 0) < 0.05)) {
        fail("motion_without_power", index, `row ${index}: ${column} moving at ${derived}/s with motor power ~0`, `${column} moved at ${derived}/s with no motor power`);
      }
    }
    for (const column of headingColumns) {
      const h0 = number(previous[column]), h1 = number(row[column]);
      if (h0 === null || h1 === null) continue;
      const step = ((h1 - h0 + 180) % 360 + 360) % 360 - 180;
      if (Math.abs(step) > limits.heading_jump_deg) {
        fail("heading_jump", index, `row ${index}: ${column} jumped ${step} degrees in one step (${h0} -> ${h1})`, `${column} jumped ${step} deg in one step`);
      }
    }
    for (const column of columns) {
      const pair = column === "x" ? ["x", "y"] : column.endsWith("_x") ? [column, `${column.slice(0, -2)}_y`] : null;
      if (!pair) continue;
      const values = [number(previous[pair[0]]), number(previous[pair[1]]), number(row[pair[0]]), number(row[pair[1]])];
      if (values.some((value) => value === null)) continue;
      const [x0, y0, x1, y1] = values;
      const speed = Math.hypot(x1 - x0, y1 - y0) / dt;
      if (speed > limits.max_speed) fail("odometry_jump", index, `row ${index}: odometry implies speed ${speed}/s, above max ${limits.max_speed}/s`, `odometry speed ${speed}/s above max ${limits.max_speed}/s`);
    }
  }

  const episodes = new Map();
  for (let index = 0; index < rows.length; index++) {
    const name = groupOf(rows[index]);
    if (!episodes.has(name)) episodes.set(name, { episode_id: name, samples: 0, flagged_samples: 0 });
    const episode = episodes.get(name);
    episode.samples++;
    if (excluded.has(index)) episode.flagged_samples++;
  }
  const intervals = [];
  for (let index = 1; index < rows.length; index++) {
    if (groupOf(rows[index - 1]) !== groupOf(rows[index])) continue;
    const t0 = number(rows[index - 1][timeKey]), t1 = number(rows[index][timeKey]);
    if (t0 !== null && t1 !== null) intervals.push(t1 - t0);
  }
  return {
    verdict: failed.size ? "failed" : "passed",
    failed_checks: [...failed].sort(([a], [b]) => a.localeCompare(b)).map(([name, details]) => ({ name, detail: details.slice(0, 5).join("; ") })),
    warnings: [...warnings].sort(([a], [b]) => a.localeCompare(b)).map(([name, details]) => ({ name, detail: details.slice(0, 5).join("; ") })),
    excluded_rows: Object.fromEntries([...excluded].sort(([a], [b]) => a - b).map(([index, reasons]) => [String(index), reasons])),
    episodes: [...episodes.values()],
    summary: { rows: rows.length, flagged_rows: excluded.size, median_dt_seconds: median(intervals) },
  };
}
