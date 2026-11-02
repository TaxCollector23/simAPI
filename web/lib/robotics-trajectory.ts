/** Episode-aware manipulation checks. Mirrors core/robotics_trajectory.py. */
export interface TrajectoryCheck {
  name: string;
  column: string;
  status: "passed" | "warning" | "failed";
  violations: number;
  detail: string;
  indices: number[];
}
export interface RoboticsSummary {
  engine_version: string;
  episodes: { episode_id: string; samples: number; duration_seconds: number | null; flagged_samples: number }[];
  time_column: string | null;
  episode_column: string | null;
  assumptions: string[];
}
const normalize = (key: string) => key.trim().toLowerCase().replace(/[ .-]/g, "_");
function numeric(value: unknown): number | null {
  if (value === null || value === undefined || typeof value === "boolean" || (typeof value === "string" && !value.trim())) return null;
  if (typeof value !== "number" && typeof value !== "string") return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

export function analyzeTrajectories(
  sourceRows: Record<string, unknown>[],
  limits: Record<string, [number, number]> = {},
  conditions: Record<string, number> = {},
): { checks: TrajectoryCheck[]; summary: RoboticsSummary } {
  const rows = sourceRows.map((row) => Object.fromEntries(Object.entries(row).map(([key, value]) => [normalize(key), value])));
  const keys = new Set(rows.flatMap((row) => Object.keys(row)));
  const timeKey = ["time", "timestamp", "simulation_time", "sim_time", "elapsed_time"].find((key) => keys.has(key));
  const groupKey = ["episode_id", "episode", "trajectory_id", "sequence_id"].find((key) => keys.has(key));
  const bounds = Object.fromEntries(Object.entries(limits).map(([key, value]) => [normalize(key), value]));
  const groups = new Map<string, number[]>();
  rows.forEach((row, index) => {
    const group = groupKey ? String(row[groupKey] ?? "(missing episode)") : "Episode 1";
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group)!.push(index);
  });
  const checks: TrajectoryCheck[] = [];
  const flagged = new Set<number>();
  function check(name: string, column: string, bad: number[], detail: string, evaluated = true) {
    const indices = [...new Set(bad)].sort((a, b) => a - b);
    checks.push({ name, column, indices, status: evaluated ? indices.length ? "failed" : "passed" : "warning", violations: indices.length, detail: evaluated ? detail : `Not evaluated. ${detail}` });
    indices.forEach((index) => flagged.add(index));
  }
  if (!timeKey) {
    check("robotics_time_coverage", "time", [], "No numeric time column: trajectory timing and derivatives were not evaluated.", false);
  } else {
    const badTime: number[] = [], badGap: number[] = [];
    const pairs: [number, number, number][] = [];
    for (const indices of groups.values()) {
      indices.forEach((index, offset) => {
        const time = numeric(rows[index][timeKey]);
        if (time === null) { badTime.push(index); return; }
        if (!offset) return;
        const prior = indices[offset - 1], previous = numeric(rows[prior][timeKey]);
        if (previous === null) return;
        const dt = time - previous;
        if (dt <= 0) { badTime.push(index); return; }
        pairs.push([prior, index, dt]);
        if (conditions.max_time_step > 0 && dt > conditions.max_time_step) badGap.push(index);
      });
    }
    check("robotics_time_order", timeKey, badTime, `${badTime.length} sample(s) have missing or non-increasing time within their episode.`);
    if (conditions.max_time_step > 0) check("robotics_sample_gaps", timeKey, badGap, `${badGap.length} interval(s) exceed the configured maximum time step of ${conditions.max_time_step} seconds.`, pairs.length > 0);
    const evaluated: Record<string, boolean> = { velocity_tolerance: false, acceleration_tolerance: false };
    for (const column of [...keys].sort()) {
      if (!column.startsWith("joint")) continue;
      for (const [quantity, derivative, option] of [
        ["position", "velocity", "velocity_tolerance"], ["velocity", "acceleration", "acceleration_tolerance"],
      ]) {
        if (!column.endsWith(`_${quantity}`)) continue;
        const target = column.slice(0, -quantity.length) + derivative;
        const limit = bounds[target], tolerance = conditions[option] ?? 0;
        const compare = tolerance > 0 && keys.has(target);
        if (!limit && !compare) continue;
        const badBound: number[] = [], badConsistency: number[] = [];
        let usable = 0;
        for (const [prior, index, dt] of pairs) {
          const first = numeric(rows[prior][column]), last = numeric(rows[index][column]);
          if (first === null || last === null) continue;
          usable++;
          const observed = (last - first) / dt;
          if (limit && (observed < limit[0] || observed > limit[1])) badBound.push(index);
          if (compare) {
            const left = numeric(rows[prior][target]), right = numeric(rows[index][target]);
            if (left === null || right === null || Math.abs(observed - (left + right) / 2) > tolerance) badConsistency.push(index);
          }
        }
        if (limit) check(`robotics_derived_limit:${target}`, target, badBound, `${badBound.length} interval(s): ${derivative} derived from ${column} exceeds [${limit[0]}, ${limit[1]}].`, usable > 0);
        if (compare) {
          evaluated[option] ||= usable > 0;
          check(`robotics_consistency:${target}`, target, badConsistency, `${badConsistency.length} interval(s): finite-difference ${derivative} differs from the endpoint-average ${target} by more than ${tolerance}.`, usable > 0);
        }
      }
    }
    for (const [option, wasEvaluated] of Object.entries(evaluated)) {
      if (conditions[option] > 0 && !wasEvaluated) check(`robotics_not_evaluated:${option}`, option, [], `${option} was requested but matching joint signals and valid adjacent timestamps were unavailable.`, false);
    }
  }
  const episodes = [...groups.entries()].map(([episode_id, indices]) => {
    const times = timeKey ? indices.map((index) => numeric(rows[index][timeKey])).filter((value): value is number => value !== null) : [];
    const ordered = times.length === indices.length && times.every((value, index) => !index || value > times[index - 1]);
    const duration = times.length >= 2 && ordered ? times[times.length - 1] - times[0] : null;
    return { episode_id, samples: indices.length, duration_seconds: duration !== null && duration >= 0 ? duration : null,
      flagged_samples: indices.filter((index) => flagged.has(index)).length };
  });
  return { checks, summary: { engine_version: "manipulation-2", episodes, time_column: timeKey ?? null, episode_column: groupKey ?? null,
    assumptions: ["Numeric timestamps are seconds.", "Joint positions must be unwrapped; no angle-wrap inference.", "Finite differences estimate interval-average motion, not peak motion."] } };
}
