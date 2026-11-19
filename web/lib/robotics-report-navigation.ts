import { normalizeFtcRows } from "./ftc-frc.js";
import { normalize, numeric, rowKeys, type Evidence, type Row } from "./robotics-workflow.js";

export const findingAnchor = "trajectory-finding";
export const sampleAnchor = "trajectory-sample";
export const sampleTableAnchor = "trajectory-sample-table";

export const ciRunFile = "simapi-run.json";
export const ciProfileFile = "simapi-profile.json";
export const ciReportFile = "simapi-report.json";
export type CiFailThreshold = "failed" | "warning";

export function ciValidationCommand(threshold: CiFailThreshold) {
  return `simapi validate ./${ciRunFile} --profile ./${ciProfileFile} --exact-profile --no-ai --report ./${ciReportFile} --fail-on ${threshold}`;
}

export function signalKey(columns: string[], signal: string | null | undefined, ftc = false) {
  if (!signal) return undefined;
  return columns.includes(signal)
    ? signal
    : columns.find((column) => normalize(column) === normalize(signal))
      ?? (ftc ? columns.find((column) => Object.hasOwn(normalizeFtcRows([{ [column]: null }])[0], signal)) : undefined);
}

export function reportRowKeys(
  rows: Row[],
  columns: string[],
  reported?: { time_column?: string | null; episode_column?: string | null },
  ftc = false,
) {
  const inferred = rowKeys(rows);
  return {
    time: signalKey(columns, reported?.time_column, ftc) ?? inferred.time ?? signalKey(columns, "t"),
    group: signalKey(columns, reported?.episode_column, ftc) ?? inferred.group,
  };
}

export function findingWindow(
  times: (number | null)[],
  sample: number,
  finding: Pick<Evidence, "check" | "time" | "interval_start" | "interval_end">,
) {
  const time = numeric(finding.time);
  if (time === null) return null;
  const stepCheck = /^(robotics_derived_limit:|robotics_consistency:|robotics_energy:|robotics_sample_gaps$|robotics_time_order$)/;
  const earlier = numeric(finding.interval_start) ??
    (stepCheck.test(finding.check) ? times[sample - 1] ?? null : null);
  const later = numeric(finding.interval_end);
  const start = Math.min(time, earlier ?? time);
  const end = Math.max(time, later ?? time);
  const nearby = times.slice(Math.max(0, sample - 3), sample + 4)
    .filter((value): value is number => value !== null);
  const left = Math.min(start, ...nearby);
  const right = Math.max(end, ...nearby);
  const padding = (right - left) * 0.12 || Math.max(Math.abs(time) * Number.EPSILON * 8, 0.001);
  return { time, start, end, left: left - padding, right: right + padding };
}

export function findingUnits(
  finding: Pick<Evidence, "signal" | "check" | "unit">,
  units: Record<string, string>,
  conversions: Record<string, string>,
) {
  const signal = normalize(finding.signal);
  const declared = signalKey(Object.keys(units), signal);
  const conversion = signalKey(Object.keys(conversions), signal);
  const [from, to] = conversion ? conversions[conversion].split("->") : [];
  if (finding.unit) return { unit: finding.unit, factor: 1 };
  if (to) {
    const factor = from === "deg" && to === "rad" || from === "deg/s" && to === "rad/s" ? Math.PI / 180 : 1;
    return { unit: to, factor };
  }
  if (finding.check === "robotics_sample_gaps" || finding.check === "robotics_time_order") {
    return { unit: "s", factor: 1 };
  }
  if (declared) return { unit: units[declared], factor: 1 };

  // The trajectory engine assumes these canonical units when no profile
  // overrides them. Generic positions and unknown signals have no assumed unit.
  const joint = signal.startsWith("joint");
  const suffix = signal.split("_").at(-1);
  const defaults: Record<string, string> = {
    position: "rad", velocity: "rad/s", acceleration: "rad/s²", torque: "N·m", effort: "N·m",
  };
  const unit = signal === "end_effector_position" || finding.check.startsWith("robotics_kinematics:") ? "m"
    : suffix === "force" ? "N"
    : joint && suffix ? defaults[suffix] : undefined;
  return { unit, factor: 1 };
}
