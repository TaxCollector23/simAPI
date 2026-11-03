"""Episode-aware trajectory checks. Time is seconds; positions are unwrapped."""
from __future__ import annotations

import math
from typing import Any

ENGINE_VERSION = "manipulation-2"
TIME_KEYS = ("time", "timestamp", "simulation_time", "sim_time", "elapsed_time")
GROUP_KEYS = ("episode_id", "episode", "trajectory_id", "sequence_id")
OPTION_KEYS = ("max_time_step", "velocity_tolerance", "acceleration_tolerance")


def normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        return None
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (ValueError, TypeError):
        return None


def analyze_trajectories(
    source_rows: list[dict[str, Any]],
    limits: dict[str, tuple[float, float]],
    conditions: dict[str, float],
) -> dict[str, Any]:
    rows = [{normalize(key): value for key, value in row.items()} for row in source_rows]
    keys = set().union(*(row.keys() for row in rows)) if rows else set()
    time_key = next((key for key in TIME_KEYS if key in keys), None)
    group_key = next((key for key in GROUP_KEYS if key in keys), None)
    bounds = {normalize(key): value for key, value in limits.items()}
    groups: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        group = str(row.get(group_key, "(missing episode)")) if group_key else "Episode 1"
        groups.setdefault(group, []).append(index)
    checks: list[dict[str, Any]] = []
    excluded: dict[int, list[str]] = {}

    def check(name: str, column: str, bad: list[int], detail: str, evaluated: bool = True) -> None:
        unique = sorted(set(bad))
        status = ("failed" if unique else "passed") if evaluated else "warning"
        checks.append({"name": name, "column": column, "status": status, "indices": unique,
                       "violations": len(unique), "detail": detail if evaluated else "Not evaluated. " + detail, "low": None, "high": None})
        for index in unique:
            excluded.setdefault(index, []).append(detail)

    if not time_key:
        check("robotics_time_coverage", "time", [], "No numeric time column: trajectory timing and derivatives were not evaluated.", False)
    else:
        bad_time: list[int] = []
        bad_gap: list[int] = []
        pairs: list[tuple[int, int, float]] = []
        for indices in groups.values():
            for offset, index in enumerate(indices):
                value = number(rows[index].get(time_key))
                if value is None:
                    bad_time.append(index)
                    continue
                if not offset:
                    continue
                prior = indices[offset - 1]
                previous = number(rows[prior].get(time_key))
                if previous is None:
                    continue
                dt = value - previous
                if dt <= 0:
                    bad_time.append(index)
                    continue
                pairs.append((prior, index, dt))
                if conditions.get("max_time_step", 0) > 0 and dt > conditions["max_time_step"]:
                    bad_gap.append(index)
        check("robotics_time_order", time_key, bad_time,
              f"{len(bad_time)} sample(s) have missing or non-increasing time within their episode.")
        if conditions.get("max_time_step", 0) > 0:
            check("robotics_sample_gaps", time_key, bad_gap,
                  f"{len(bad_gap)} interval(s) exceed the configured maximum time step of {conditions['max_time_step']:g} seconds.", bool(pairs))

        evaluated = {"velocity_tolerance": False, "acceleration_tolerance": False}
        for column in sorted(keys):
            # Derivatives only use explicitly named joint state signals.
            if not column.startswith("joint"):
                continue
            for quantity, derivative, option in (
                ("position", "velocity", "velocity_tolerance"),
                ("velocity", "acceleration", "acceleration_tolerance"),
            ):
                if not column.endswith("_" + quantity):
                    continue
                target = column[:-len(quantity)] + derivative
                limit = bounds.get(target)
                tolerance = conditions.get(option, 0)
                compare = tolerance > 0 and target in keys
                if limit is None and not compare:
                    continue
                bad_bound: list[int] = []
                bad_consistency: list[int] = []
                usable = 0
                for prior, index, dt in pairs:
                    first = number(rows[prior].get(column))
                    last = number(rows[index].get(column))
                    if first is None or last is None:
                        continue
                    usable += 1
                    observed = (last - first) / dt
                    if limit is not None and not limit[0] <= observed <= limit[1]:
                        bad_bound.append(index)
                    if compare:
                        left = number(rows[prior].get(target))
                        right = number(rows[index].get(target))
                        if left is None or right is None or abs(observed - (left + right) / 2) > tolerance:
                            bad_consistency.append(index)
                if limit is not None:
                    check(f"robotics_derived_limit:{target}", target, bad_bound,
                          f"{len(bad_bound)} interval(s): {derivative} derived from {column} exceeds [{limit[0]:g}, {limit[1]:g}].", usable > 0)
                if compare:
                    evaluated[option] = evaluated[option] or usable > 0
                    check(f"robotics_consistency:{target}", target, bad_consistency,
                          f"{len(bad_consistency)} interval(s): finite-difference {derivative} differs from the endpoint-average {target} by more than {tolerance:g}.", usable > 0)
        for option, was_evaluated in evaluated.items():
            if conditions.get(option, 0) > 0 and not was_evaluated:
                check(f"robotics_not_evaluated:{option}", option, [],
                      f"{option} was requested but matching joint signals and valid adjacent timestamps were unavailable.", False)

    episodes = []
    for name, indices in groups.items():
        times = [number(rows[index].get(time_key)) for index in indices] if time_key else []
        valid_times = [value for value in times if value is not None]
        ordered = len(valid_times) == len(indices) and all(last > first for first, last in zip(valid_times, valid_times[1:], strict=False))
        duration = valid_times[-1] - valid_times[0] if len(valid_times) >= 2 and ordered else None
        episodes.append({"episode_id": name, "samples": len(indices),
                         "duration_seconds": duration if duration is not None and duration >= 0 else None,
                         "flagged_samples": sum(index in excluded for index in indices)})
    return {"checks": checks, "excluded": excluded,
            "summary": {"engine_version": ENGINE_VERSION, "episodes": episodes,
                        "time_column": time_key, "episode_column": group_key,
                        "assumptions": ["Numeric timestamps are seconds.", "Joint positions must be unwrapped; no angle-wrap inference.",
                                        "Finite differences estimate interval-average motion, not peak motion."]}}
