import { FTC_DEFAULT_LIMITS } from "./ftc-frc.js";
/** Shared robotics workflow helpers. Run scripts/sync-robotics.mjs after edits. */
export const normalize = (v) =>
  String(v)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "");
export const jointStem = (name) => {
  const key = normalize(name);
  if (!key) throw new Error("Invalid joint name.");
  return key.startsWith("joint") ? key : `joint_${key}`;
};
export const numeric = (v) =>
  (typeof v === "number" || (typeof v === "string" && v.trim())) &&
  Number.isFinite(Number(v))
    ? Number(v)
    : null;
const timeNames = [
    "time",
    "timestamp",
    "simulation_time",
    "sim_time",
    "elapsed_time",
  ],
  groupNames = ["episode_id", "episode", "trajectory_id", "sequence_id"];
export function rowKeys(rows) {
  const keys = [...new Set(rows.flatMap(Object.keys))];
  return {
    time: keys.find((k) => timeNames.includes(normalize(k))),
    group: keys.find((k) => groupNames.includes(normalize(k))),
  };
}
export const episodeOf = (row, key) =>
  key ? String(row[key] ?? "(missing episode)") : "Episode 1";
export function validateProfile(value) {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Profile must be a JSON object.");
  const structured =
    "robotics_limits" in value ||
    "conditions" in value ||
    "schema_version" in value ||
    "robotics_profile" in value ||
    "ftc_limits" in value ||
    "units" in value;
  const limits = structured ? (value.robotics_limits ?? {}) : value,
    keys = new Set();
  if (!limits || typeof limits !== "object" || Array.isArray(limits))
    throw new Error("robotics_limits must be a signal-to-range map.");
  for (const [key, range] of Object.entries(limits)) {
    if (!normalize(key) || keys.has(normalize(key)))
      throw new Error(`Duplicate or invalid signal: ${key}`);
    keys.add(normalize(key));
    if (
      !Array.isArray(range) ||
      range.length !== 2 ||
      !range.every((v) => typeof v === "number" && Number.isFinite(v)) ||
      range[0] >= range[1]
    )
      throw new Error(`Invalid range for ${key}. Use [minimum, maximum].`);
  }
  const conditions = structured ? (value.conditions ?? {}) : {};
  const units = structured ? (value.units ?? {}) : {};
  if (!units || typeof units !== "object" || Array.isArray(units) || Object.values(units).some((unit) => typeof unit !== "string"))
    throw new Error("Profile units must map signal names to unit strings.");
  let roboticsProfile = String(value.robotics_profile ?? "robotics").toLowerCase();
  if (roboticsProfile === "frc") roboticsProfile = "ftc";
  if (!["robotics", "ftc"].includes(roboticsProfile))
    throw new Error("robotics_profile must be 'robotics' or 'ftc'.");
  const ftcLimits = roboticsProfile === "ftc" ? { ...structuredClone(FTC_DEFAULT_LIMITS), ...(value.ftc_limits ?? {}) } : (value.ftc_limits ?? {});
  if (!ftcLimits || typeof ftcLimits !== "object" || Array.isArray(ftcLimits))
    throw new Error("ftc_limits must be an FTC/FRC limit map.");
  if (roboticsProfile === "ftc") {
    const rangeKeys = new Set(["motor_power", "battery_voltage"]);
    const allowedKeys = new Set([
      "motor_power", "battery_voltage", "battery_sag_voltage",
      "sag_min_total_power", "velocity_tolerance", "min_moving_speed",
      "max_speed", "heading_jump_deg",
    ]);
    for (const [key, setting] of Object.entries(ftcLimits)) {
      if (!allowedKeys.has(key)) throw new Error(`Unknown FTC/FRC limit: ${key}`);
      if (rangeKeys.has(key)) {
        if (!Array.isArray(setting) || setting.length !== 2 ||
            !setting.every((n) => typeof n === "number" && Number.isFinite(n)) || setting[0] >= setting[1])
          throw new Error(`Invalid FTC/FRC range for ${key}.`);
      } else if (typeof setting !== "number" || !Number.isFinite(setting) || setting < 0) {
        throw new Error(`Invalid FTC/FRC limit for ${key}.`);
      }
    }
  }
  if (
    !conditions ||
    typeof conditions !== "object" ||
    Array.isArray(conditions) ||
    Object.values(conditions).some(
      (v) => typeof v !== "number" || !Number.isFinite(v),
    )
  )
    throw new Error("Profile conditions must be finite numbers.");
  for (const key of [
    "max_time_step",
    "velocity_tolerance",
    "acceleration_tolerance",
  ])
    if (conditions[key] !== undefined && conditions[key] <= 0)
      throw new Error(`${key} must be positive.`);
  return {
    ...(structured ? value : {}),
    schema_version: 1,
    name: typeof value.name === "string" ? value.name : roboticsProfile === "ftc" ? "FTC / FRC (school robotics)" : "Arm profile",
    ...(value.robotics_profile !== undefined ? { robotics_profile: roboticsProfile } : {}),
    robotics_limits: limits,
    ...(roboticsProfile === "ftc" ? { ftc_limits: ftcLimits } : {}),
    ...(Object.keys(units).length ? { units } : {}),
    conditions,
  };
}
export function toCsv(rows) {
  if (!rows.length) return "";
  const columns = [...new Set(rows.flatMap(Object.keys))],
    cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  return (
    [
      columns.map(cell).join(","),
      ...rows.map((r) => columns.map((k) => cell(r[k])).join(",")),
    ].join("\n") + "\n"
  );
}
export function parseCsvDocument(source) {
  const matrix = [],
    sourceLines = [];
  let physicalLine = 1,
    recordStart = 1;
  let row = [],
    cell = "",
    quoted = false;
  for (let i = 0; i < source.length; i++) {
    const c = source[i];
    if (quoted) {
      if (c === "\n" || (c === "\r" && source[i + 1] !== "\n")) physicalLine++;
      if (c === '"' && source[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"' && !cell) quoted = true;
    else if (c === ",") {
      row.push(cell);
      cell = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && source[i + 1] === "\n") i++;
      row.push(cell);
      physicalLine++;
      if (row.some((v) => v.trim())) {
        matrix.push(row);
        sourceLines.push(recordStart);
      }
      recordStart = physicalLine;
      row = [];
      cell = "";
    } else cell += c;
  }
  row.push(cell);
  if (row.some((v) => v.trim())) {
    matrix.push(row);
    sourceLines.push(recordStart);
  }
  if (quoted || matrix.length < 2)
    throw new Error("CSV needs a header and at least one complete sample row.");
  const headers = matrix
    .shift()
    .map((v, i) => v.trim().replace(i ? /$^/ : /^\uFEFF/, ""));
  if (
    headers.some((v) => !v) ||
    new Set(headers.map(normalize)).size !== headers.length
  )
    throw new Error(
      "CSV columns must be present and unique after normalization.",
    );
  sourceLines.shift();
  const rows = matrix.map((values, i) => {
    if (values.length !== headers.length)
      throw new Error(`CSV row ${i + 2} has the wrong number of columns.`);
    return Object.fromEntries(
      headers.map((k, j) => [
        k,
        groupNames.includes(normalize(k))
          ? values[j].trim()
          : values[j].trim() === ""
            ? null
            : (numeric(values[j]) ?? values[j].trim()),
      ]),
    );
  });
  return { rows, sourceLines };
}
export function parseCsv(source) {
  return parseCsvDocument(source).rows;
}
const stable = (v) =>
  JSON.stringify(v, (_, x) =>
    x && typeof x === "object" && !Array.isArray(x)
      ? Object.fromEntries(
          Object.entries(x).sort(([a], [b]) => a.localeCompare(b)),
        )
      : x,
  );
export function compareReports(before, after) {
  for (const r of [before, after])
    if (!r || !["passed", "warning", "failed"].includes(r.status))
      throw new Error("Choose two SimAPI validation reports.");
  const rank = { passed: 0, warning: 1, failed: 2 },
    checks = (r) => {
      const map = new Map();
      for (const x of [...(r.issues ?? []), ...(r.robotics_checks ?? [])])
        if (!map.has(x.name) || rank[x.status] > rank[map.get(x.name).status])
          map.set(x.name, x);
      return map;
    };
  const a = checks(before),
    b = checks(after),
    introduced = [],
    resolved = [],
    persisting = [];
  for (const name of new Set([...a.keys(), ...b.keys()])) {
    const old = a.get(name)?.status ?? "passed",
      next = b.get(name)?.status ?? "passed",
      entry = { name, before: old, after: next };
    if (rank[next] > rank[old]) introduced.push(entry);
    else if (rank[next] < rank[old]) resolved.push(entry);
    else if (rank[next] > 0) persisting.push(entry);
  }
  const episodes = new Map(
      (before.robotics_summary?.episodes ?? []).map((e) => [e.episode_id, e]),
    ),
    episodeChanges = [];
  for (const e of after.robotics_summary?.episodes ?? []) {
    const previous = episodes.get(e.episode_id);
    episodes.delete(e.episode_id);
    if (
      !previous ||
      previous.flagged_samples !== e.flagged_samples ||
      previous.samples !== e.samples
    )
      episodeChanges.push({
        episode_id: e.episode_id,
        before: previous ?? null,
        after: e,
      });
  }
  for (const e of episodes.values())
    episodeChanges.push({ episode_id: e.episode_id, before: e, after: null });
  const known = Boolean(before.validation_context && after.validation_context);
  return {
    status_before: before.status,
    status_after: after.status,
    context_known: known,
    same_configuration: known
      ? stable(before.validation_context) === stable(after.validation_context)
      : null,
    introduced,
    resolved,
    persisting,
    episode_changes: episodeChanges,
    exclusion_delta:
      (after.trials_excluded ?? 0) - (before.trials_excluded ?? 0),
    regressed:
      rank[after.status] > rank[before.status] || introduced.length > 0,
  };
}
export function repairPreview(source) {
  if (
    !Array.isArray(source) ||
    !source.length ||
    source.some((r) => !r || typeof r !== "object" || Array.isArray(r))
  )
    throw new Error("Repair needs a non-empty array of sample objects.");
  const { time, group } = rowKeys(source),
    proposals = [],
    unrepairable = [];
  let rows = source.map((r) => ({ ...r }));
  if (time) {
    const dropped = [],
      seen = new Set();
    rows = rows.filter((row, index) => {
      const id = stable(row);
      if (numeric(row[time]) !== null && seen.has(id)) {
        dropped.push(index);
        return false;
      }
      seen.add(id);
      return true;
    });
    if (dropped.length)
      proposals.push({
        kind: "duplicate_samples",
        description:
          "Remove exact repeated samples with the same timestamp and episode.",
        affected_row_count: dropped.length,
        changes: [],
        rows_dropped: dropped,
      });
  }
  const groups = new Map();
  rows.forEach((row, i) => {
    const id = episodeOf(row, group);
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id).push(i);
  });
  for (const [id, indices] of groups) {
    if (!time || indices.some((i) => numeric(rows[i][time]) === null)) {
      unrepairable.push({
        reason: `${id}: missing numeric time; reordering and interpolation were skipped.`,
      });
      continue;
    }
    const timestamps = indices.map((i) => numeric(rows[i][time]));
    if (new Set(timestamps).size !== timestamps.length) {
      unrepairable.push({
        reason: `${id}: conflicting samples share a timestamp; select the correct sample manually.`,
      });
      continue;
    }
    const sorted = indices
      .map((i) => rows[i])
      .sort((a, b) => numeric(a[time]) - numeric(b[time]));
    if (indices.some((index, offset) => rows[index] !== sorted[offset])) {
      proposals.push({
        kind: "time_order",
        description: `Order samples by time within ${id}; episode membership is preserved.`,
        affected_row_count: indices.length,
        changes: [],
        rows_dropped: [],
      });
      indices.forEach((i, n) => {
        rows[i] = sorted[n];
      });
    }
    const keys = [
      ...new Set(indices.flatMap((i) => Object.keys(rows[i]))),
    ].filter(
      (k) =>
        k !== time &&
        k !== group &&
        /^(joint|end_effector|tool|gripper)/.test(normalize(k)),
    );
    for (const key of keys)
      for (let offset = 1; offset < indices.length - 1; offset++) {
        if (numeric(rows[indices[offset]][key]) !== null) continue;
        const start = offset;
        while (
          offset < indices.length &&
          numeric(rows[indices[offset]][key]) === null
        )
          offset++;
        if (offset - start > 2 || offset >= indices.length) continue;
        const left = rows[indices[start - 1]],
          right = rows[indices[offset]],
          lv = numeric(left[key]),
          rv = numeric(right[key]);
        if (lv === null || rv === null) continue;
        const changes = [];
        for (let j = start; j < offset; j++) {
          const row = rows[indices[j]],
            after =
              lv +
              ((rv - lv) * (numeric(row[time]) - numeric(left[time]))) /
                (numeric(right[time]) - numeric(left[time]));
          changes.push({
            row: indices[j],
            column: key,
            before: row[key] ?? null,
            after,
          });
          row[key] = after;
        }
        proposals.push({
          kind: "short_gap",
          description: `Interpolate ${key} within ${id}. Review before using the repaired data.`,
          affected_row_count: changes.length,
          changes,
          rows_dropped: [],
        });
      }
  }
  return {
    proposals,
    unrepairable,
    repaired_data: rows,
    original_samples: source.length,
    repaired_samples: rows.length,
  };
}
export function buildEvidence(
  source,
  checks = [],
  limits = {},
  conditions = {},
) {
  const rows = source.map((r) =>
      Object.fromEntries(Object.entries(r).map(([k, v]) => [normalize(k), v])),
    ),
    { time, group } = rowKeys(rows),
    evidence = [],
    previous = new Map(),
    last = new Map();
  rows.forEach((r, i) => {
    const id = episodeOf(r, group);
    previous.set(i, last.get(id));
    last.set(id, i);
  });
  let total = 0;
  const push = (i, signal, check, observed, expected, detail) => {
    total++;
    if (evidence.length < 1000)
      evidence.push({
        check,
        status: "failed",
        signal,
        episode_id: episodeOf(rows[i], group),
        sample_index: i,
        time: time ? numeric(rows[i][time]) : null,
        observed,
        expected,
        detail,
      });
  };
  const bounds = Object.fromEntries(
    Object.entries(limits).map(([k, v]) => [normalize(k), v]),
  );
  for (const [signal, range] of Object.entries(bounds))
    rows.forEach((row, i) => {
      const v = numeric(row[signal]);
      if (v === null || v < range[0] || v > range[1])
        push(
          i,
          signal,
          `robotics_limit:${signal}`,
          v,
          range,
          v === null
            ? "Signal is missing or non-numeric."
            : "Outside the configured range.",
        );
    });
  for (const check of checks)
    for (const i of check.indices ?? []) {
      if (!rows[i]) continue;
      const signal = check.column,
        left = rows[previous.get(i)],
        row = rows[i];
      let observed = numeric(row[signal]),
        expected = null;
      if (
        check.name.startsWith("robotics_derived_limit:") ||
        check.name.startsWith("robotics_consistency:")
      ) {
        const from = signal.endsWith("_acceleration")
            ? signal.replace(/acceleration$/, "velocity")
            : signal.replace(/velocity$/, "position"),
          dt = left && time ? numeric(row[time]) - numeric(left[time]) : 0;
        observed =
          dt > 0 && numeric(row[from]) !== null && numeric(left[from]) !== null
            ? (numeric(row[from]) - numeric(left[from])) / dt
            : null;
        expected = bounds[signal] ?? null;
        if (check.name.startsWith("robotics_consistency:")) {
          const option = signal.endsWith("_acceleration")
              ? "acceleration_tolerance"
              : "velocity_tolerance",
            avg =
              left &&
              numeric(left[signal]) !== null &&
              numeric(row[signal]) !== null
                ? (numeric(left[signal]) + numeric(row[signal])) / 2
                : null;
          expected =
            avg !== null
              ? [avg - conditions[option], avg + conditions[option]]
              : null;
        }
      } else if (check.name === "robotics_sample_gaps" && left && time) {
        observed = numeric(row[time]) - numeric(left[time]);
        expected = [0, conditions.max_time_step];
      }
      push(i, signal, check.name, observed, expected, check.detail);
    }
  return { entries: evidence, total, truncated: total > evidence.length };
}
export function githubAnnotations(report, file, sourceLines) {
  const data = (v) =>
      String(v)
        .replace(/%/g, "%25")
        .replace(/\r/g, "%0D")
        .replace(/\n/g, "%0A"),
    prop = (v) => data(v).replace(/:/g, "%3A").replace(/,/g, "%2C");
  const entries = report.robotics_evidence?.length
    ? report.robotics_evidence
    : (report.issues ?? []).map((i) => ({
        check: i.name,
        status: i.status,
        detail: i.detail,
      }));
  return entries.slice(0, 50).map((e) => {
    const where =
      e.sample_index === undefined
        ? ""
        : `Episode ${e.episode_id}, sample ${e.sample_index + 1}, ${e.signal}${e.time === null ? "" : ` at ${e.time}s`}: `;
    const line =
      file.toLowerCase().endsWith(".csv") &&
      sourceLines?.[e.sample_index] !== undefined
        ? `,line=${sourceLines[e.sample_index]}`
        : "";
    return `::${e.status === "warning" ? "warning" : "error"} file=${prop(file)}${line},title=${prop(e.check)}::${data(where + e.detail)}`;
  });
}

export function inspectRows(rows) {
  if (
    !Array.isArray(rows) ||
    !rows.length ||
    rows.some((row) => !row || typeof row !== "object" || Array.isArray(row))
  )
    throw new Error("No sample records to inspect.");
  const { time, group } = rowKeys(rows),
    groups = new Map();
  rows.forEach((row) => {
    const id = episodeOf(row, group);
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id).push(row);
  });
  const episodes = [...groups].map(([episode_id, items]) => {
    const times = time ? items.map((row) => numeric(row[time])) : [];
    const ordered =
      times.length > 1 &&
      times.every((v, i) => v !== null && (!i || v > times[i - 1]));
    return {
      episode_id,
      samples: items.length,
      duration_seconds: ordered ? times.at(-1) - times[0] : null,
    };
  });
  const signals = [...new Set(rows.flatMap(Object.keys))]
    .filter((key) => key !== time && key !== group)
    .map((name) => {
      const values = rows
        .map((row) => numeric(row[name]))
        .filter((v) => v !== null);
      return {
        name,
        numeric_samples: values.length,
        missing_or_nonnumeric: rows.length - values.length,
        min: values.length ? Math.min(...values) : null,
        max: values.length ? Math.max(...values) : null,
      };
    });
  return {
    samples: rows.length,
    time_column: time ?? null,
    episode_column: group ?? null,
    episodes,
    signals,
  };
}
