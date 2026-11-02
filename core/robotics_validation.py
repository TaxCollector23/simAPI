"""Focused robot manipulation limits for trajectory and arm simulation data."""
from __future__ import annotations

from typing import Any

import pandas as pd

from core.robotics_trajectory import analyze_trajectories

# Broad plausibility guards inherited from the original robotics validator.
# Robot-specific values should be passed in `robotics_limits` from URDF or
# controller configuration; these defaults are not substitutes for those limits.
DEFAULT_ROBOTICS_LIMITS: dict[str, tuple[float, float]] = {
    "joint_torque": (-100_000.0, 100_000.0),
    "joint_velocity": (-500.0, 500.0),
    "joint_acceleration": (-5_000.0, 5_000.0),
    "joint_position": (-4 * 3.141592653589793, 4 * 3.141592653589793),
    "end_effector_force": (-50_000.0, 50_000.0),
    "end_effector_torque": (-10_000.0, 10_000.0),
    "end_effector_velocity": (0.0, 200.0),
    "position_error": (0.0, 500.0),
    "manipulability": (0.0, 500.0),
    "condition_number": (1.0, 1e9),
    "power_consumption": (0.0, 1e7),
    "efficiency": (0.0, 1.0),
    "settling_time": (0.0, 1_000.0),
    "overshoot": (0.0, 5.0),
    "rise_time": (0.0, 1_000.0),
    "workspace_volume": (0.0, 1e6),
}


def _key(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")


def check_robotics_limits(
    data: pd.DataFrame,
    configured_limits: dict[str, tuple[float, float]] | None = None,
    source_rows: list[dict[str, Any]] | None = None,
    conditions: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Check default and caller-declared bounds, returning per-column evidence.

    Caller-declared limits replace the broad defaults for the same canonical
    column. Missing requested columns fail closed because the limit was not
    actually evaluated.
    """
    limits = dict(DEFAULT_ROBOTICS_LIMITS)
    for column in data.columns:
        canonical = _key(column)
        if canonical.startswith("joint"):
            for quantity in ("position", "velocity", "acceleration", "torque"):
                if canonical.endswith("_" + quantity):
                    limits[canonical] = DEFAULT_ROBOTICS_LIMITS["joint_" + quantity]
    if configured_limits:
        limits.update({_key(column): (float(bounds[0]), float(bounds[1]))
                       for column, bounds in configured_limits.items()})

    columns = {_key(column): column for column in data.columns}
    checks: list[dict[str, Any]] = []
    excluded: dict[int, list[str]] = {}

    for canonical, (low, high) in limits.items():
        source_column = columns.get(canonical)
        if source_column is None:
            # Only require caller-specified columns. Default checks are
            # conditional on the simulation actually containing that signal.
            if configured_limits and canonical in {_key(c) for c in configured_limits}:
                checks.append({
                    "name": f"robotics_limit:{canonical}",
                    "column": canonical,
                    "status": "failed",
                    "low": low,
                    "high": high,
                    "violations": 0,
                    "detail": f"Configured limit was not evaluated because column '{canonical}' is missing.",
                })
                for row in data.index:
                    excluded.setdefault(int(row), []).append(
                        f"configured signal '{canonical}' is missing"
                    )
            continue

        values = pd.to_numeric(data[source_column], errors="coerce")
        outside = values.isna() | values.isin([float("inf"), float("-inf")]) | (values < low) | (values > high)
        bad_rows = [int(index) for index in data.index[outside]]
        status = "failed" if bad_rows else "passed"
        detail = (
            f"{len(bad_rows)} sample(s) missing, non-finite, or outside [{low:g}, {high:g}]"
            if bad_rows else f"All samples within [{low:g}, {high:g}]"
        )
        checks.append({
            "name": f"robotics_limit:{canonical}",
            "column": str(source_column),
            "status": status,
            "low": low,
            "high": high,
            "violations": len(bad_rows),
            "detail": detail,
        })
        for row in bad_rows:
            value = float(values.loc[row])
            excluded.setdefault(row, []).append(
                f"{source_column}={value:g} outside [{low:g}, {high:g}]"
            )

    trajectory = analyze_trajectories(
        source_rows if source_rows is not None else data.to_dict("records"),
        configured_limits or {}, conditions or {},
    )
    checks.extend(trajectory["checks"])
    for row, reasons in trajectory["excluded"].items():
        excluded.setdefault(row, []).extend(reasons)
    summary = trajectory["summary"]
    # Include all bound failures in the episode counts as well as trajectory failures.
    source = source_rows if source_rows is not None else data.to_dict("records")
    group_key = summary["episode_column"]
    counts: dict[str, int] = {}
    for row in excluded:
        record = {_key(key): value for key, value in source[row].items()}
        group = str(record.get(group_key, "(missing episode)")) if group_key else "Episode 1"
        counts[group] = counts.get(group, 0) + 1
    for episode in summary["episodes"]:
        episode["flagged_samples"] = counts.get(episode["episode_id"], 0)
    return {"checks": checks, "excluded": excluded, "summary": summary}
