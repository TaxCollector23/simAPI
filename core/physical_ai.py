"""
physical_ai.py — quality tools for Physical AI training data.

Drop this file into the SimAPI repo at:  core/physical_ai.py

Physical AI = AI that learns to move real robots. It trains on *episodes*
(one full attempt at a task, e.g. "pick up the cup" from start to finish).
If some episodes contain lying numbers (a joint teleports, a sensor freezes,
the camera clock is out of sync), the AI learns the lies.

This module answers four questions about a dataset:

  1. episode_quality(...)          Which episodes are good / bad, and WHY
                                   (plain failure labels, not just "failed").
  2. check_stream_sync(...)        Do the camera / state / action clocks
                                   agree with each other?
  3. action_state_consistency(...) Did the robot actually DO what the
                                   recorded action told it to do?
  4. export_clean_dataset(...)     Give me back ONLY the good episodes,
                                   whole, ready to train on.

Words used below:
  - "signal"  = one measured column, e.g. joint_1_position.
  - "torque"  = how hard a motor pushes (also called "effort" in ROS data).
  - "saturation" = a motor pinned at its maximum — it was struggling.

Only dependency beyond the standard library: pandas + SimAPI's own
core/robotics_validation.py (the existing checker — this file adds the
Physical-AI layer on top of it, it does not replace it).
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

try:  # normal case: this file lives in simapi/core/
    from core.robotics_validation import check_robotics_limits
except ImportError:  # imported as a sibling module inside core/
    from robotics_validation import check_robotics_limits

__all__ = [
    "FAILURE_LABELS",
    "episode_quality",
    "check_stream_sync",
    "action_state_consistency",
    "export_clean_dataset",
]

# The fixed label vocabulary. Keeping this list small and fixed means a
# report from March means the same thing as a report from October.
FAILURE_LABELS = (
    "teleport",              # implied speed breaks the velocity limit
    "limit_violation",       # a value left its allowed range
    "torque_saturation",     # motor pinned at its limit for a long stretch
    "frozen_sensor",         # a signal stopped changing while others moved
    "time_gap",              # silent hole in the timestamps
    "time_disorder",         # time went backwards / repeated
    "inconsistent_velocity", # recorded velocity disagrees with the positions
    "kinematics_mismatch",   # reported end-effector position disagrees with URDF FK
    "kinematics_unavailable", # requested FK comparison could not evaluate every sample
)

EPISODE_KEYS = ("episode_id", "episode", "trajectory_id", "sequence_id")
TIME_KEYS = ("time", "t", "timestamp", "simulation_time", "sim_time", "elapsed_time")


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _episode_key_name(rows: list[dict[str, Any]]) -> str | None:
    normalized_keys = {
        str(key).strip().lower().replace("-", "_").replace(" ", "_")
        for row in rows for key in row
    }
    for key in EPISODE_KEYS:
        if key in normalized_keys:
            return key
    return None


def _episode_value(row: dict[str, Any], key: str, default: Any = None) -> Any:
    for source_key, value in row.items():
        normalized = str(source_key).strip().lower().replace("-", "_").replace(" ", "_")
        if normalized == key:
            return value
    return default


def _group_episodes(rows: list[dict[str, Any]]):
    """Yield (episode_id, [(global_index, row), ...]) in first-seen order."""
    key = _episode_key_name(rows)
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    order: list[str] = []
    for idx, row in enumerate(rows):
        name = str(_episode_value(row, key, "(missing episode)")) if key else "Episode 1"
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append((idx, row))
    return [(name, groups[name]) for name in order]


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _clean_limits(robotics_limits: dict | None) -> dict[str, tuple[float, float]]:
    """Validate per-signal bounds before they reach the engine."""
    if robotics_limits is None:
        return {}
    if not isinstance(robotics_limits, Mapping):
        raise ValueError("robotics_limits must be a signal-to-range mapping")

    cleaned: dict[str, tuple[float, float]] = {}
    for name, rng in robotics_limits.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("robotics_limits signal names must be non-empty strings")
        if isinstance(rng, (str, bytes)):
            raise ValueError(
                f"robotics_limits[{name!r}] must be a [min, max] pair of finite numbers, got {rng!r}"
            )
        try:
            lo, hi = rng
            low, high = _num(lo), _num(hi)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"robotics_limits[{name!r}] must be a [min, max] pair of finite numbers, got {rng!r}"
            ) from exc
        if low is None or high is None:
            raise ValueError(
                f"robotics_limits[{name!r}] must contain finite numeric bounds, got {rng!r}"
            )
        if low >= high:
            raise ValueError(
                f"robotics_limits[{name!r}] minimum must be less than maximum: {rng!r}"
            )
        cleaned[name] = (low, high)
    return cleaned


def _clean_conditions(conditions: dict[str, float] | None) -> dict[str, float]:
    if conditions is None:
        return {}
    if not isinstance(conditions, Mapping):
        raise ValueError("conditions must be a mapping of names to finite numbers")
    cleaned = dict(conditions)
    for name in ("max_time_step", "velocity_tolerance", "acceleration_tolerance"):
        if name not in cleaned:
            continue
        value = _num(cleaned[name])
        if value is None or value <= 0:
            raise ValueError(f"conditions[{name!r}] must be a finite positive number")
        cleaned[name] = value
    return cleaned


# --------------------------------------------------------------------------
# extra per-episode detectors the base engine does not have
# --------------------------------------------------------------------------

def _torque_saturation_labels(ep_rows: list[dict[str, Any]],
                              limits: dict[str, tuple[float, float]]) -> list[str]:
    """A torque/effort signal sitting within 1% of its limit for >= 30% of
    samples means the motor was maxed out for a long stretch — the episode
    is a struggle, not a clean demonstration."""
    labels = []
    for column, (lo, hi) in limits.items():
        if "torque" not in column and "effort" not in column:
            continue
        source_column = column
        if not any(source_column in row for row in ep_rows):
            alias = "effort" if column.endswith("torque") else "torque"
            candidate = column.removesuffix("torque" if alias == "effort" else "effort") + alias
            if any(candidate in row for row in ep_rows):
                source_column = candidate
        values = [v for v in (_num(r.get(source_column)) for r in ep_rows) if v is not None]
        if len(values) < 4:
            continue
        width = hi - lo
        if width <= 0:
            continue
        near = sum(1 for v in values
                   if v >= hi - 0.01 * width or v <= lo + 0.01 * width)
        if near / len(values) >= 0.30:
            labels.append("torque_saturation")
            break
    return labels


def _frozen_sensor_labels(ep_rows: list[dict[str, Any]]) -> list[str]:
    """A joint POSITION that is exactly the same for >= 5 samples in a row,
    while another joint position is moving in that same window, usually
    means the sensor/encoder froze (a genuinely still robot holds ALL
    joints still, so that is not flagged).

    Only *_position signals are checked: a constant velocity or torque
    during a steady move is normal (cruising), a constant position while
    the rest of the arm moves is not."""
    joint_cols = sorted({
        k for row in ep_rows for k, v in row.items()
        if k.startswith("joint") and k.endswith("_position") and _num(v) is not None
    })
    if len(joint_cols) < 2 or len(ep_rows) < 5:
        return []
    series = {c: [_num(r.get(c)) for r in ep_rows] for c in joint_cols}
    for col in joint_cols:
        vals = series[col]
        start = 0
        for i in range(1, len(vals) + 1):
            if i == len(vals) or vals[i] != vals[start]:
                run_len = i - start
                if run_len >= 5 and vals[start] is not None:
                    window = range(start, i)
                    others_move = any(
                        len({series[o][j] for j in window if series[o][j] is not None}) > 1
                        for o in joint_cols if o != col
                    )
                    if others_move:
                        return ["frozen_sensor"]
                start = i
    return []


_LABEL_BY_CHECK = (
    ("robotics_derived_limit", "teleport"),
    ("robotics_consistency", "inconsistent_velocity"),
    ("robotics_sample_gaps", "time_gap"),
    ("robotics_time_order", "time_disorder"),
    ("robotics_limit", "limit_violation"),
)


def _labels_from_checks(checks: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    for check in checks:
        if check.get("status") != "failed":
            continue
        for prefix, label in _LABEL_BY_CHECK:
            if str(check.get("name", "")).startswith(prefix) and label not in labels:
                labels.append(label)
    return labels


# --------------------------------------------------------------------------
# 1. per-episode quality
# --------------------------------------------------------------------------

def episode_quality(rows: list[dict[str, Any]],
                    robotics_limits: dict[str, tuple[float, float]] | None = None,
                    conditions: dict[str, float] | None = None) -> dict[str, Any]:
    """Score every episode in `rows`.

    rows: one dict per sample, like the rest of SimAPI:
          {"episode_id": "pick_cup_01", "time": 0.02,
           "joint_1_position": 0.02, "joint_1_velocity": 1.0, ...}
    robotics_limits: allowed (min, max) per signal, the robot's own limits.
    conditions: passed through to the base checker (max_time_step,
          velocity_tolerance, acceleration_tolerance).

    Returns {"episodes": [...], "verdict": ..., "summary": {...}} where each
    episode entry has: episode_id, samples, verdict, failure_labels,
    flagged_rows (positions in the original `rows` list), failed_checks,
    training_ready.
    """
    limits = _clean_limits(robotics_limits)
    checked_conditions = _clean_conditions(conditions)
    if not rows:
        # Fail closed: an empty dataset is not training data.
        return {
            "episodes": [],
            "verdict": "failed",
            "detail": "No rows provided — nothing to validate.",
            "summary": {"episodes": 0, "training_ready_episodes": 0,
                        "removed_episodes": 0, "flagged_rows": 0,
                        "total_rows": 0},
        }
    episodes_out = []
    total_flagged = 0
    for name, members in _group_episodes(rows):
        ep_rows = [row for _, row in members]
        global_idx = [idx for idx, _ in members]
        report = check_robotics_limits(
            pd.DataFrame(ep_rows), limits, source_rows=ep_rows,
            conditions=checked_conditions,
        )
        failed = [c for c in report.get("checks", []) if c.get("status") == "failed"]
        unprofiled_warning = any(
            c.get("name") == "robotics_unprofiled_signal" and c.get("status") == "warning"
            for c in report.get("checks", [])
        )
        labels = _labels_from_checks(report.get("checks", []))
        for extra in (_torque_saturation_labels(ep_rows, limits)
                      + _frozen_sensor_labels(ep_rows)):
            if extra not in labels:
                labels.append(extra)
        local_excluded = sorted((report.get("excluded") or {}).keys())
        flagged_rows = [global_idx[i] for i in local_excluded if i < len(global_idx)]
        total_flagged += len(flagged_rows)
        bad = bool(failed) or bool(labels)
        warning_only = not bad and unprofiled_warning
        episodes_out.append({
            "episode_id": name,
            "samples": len(ep_rows),
            "verdict": "failed" if bad else "warning" if warning_only else "passed",
            "failure_labels": labels,
            "flagged_rows": flagged_rows,
            "failed_checks": [
                {"name": c["name"], "detail": c.get("detail", "")} for c in failed
            ],
            "training_ready": not bad and not unprofiled_warning,
        })
    bad_eps = [e for e in episodes_out if not e["training_ready"]]
    failed_eps = [e for e in episodes_out if e["verdict"] == "failed"]
    warning_eps = [e for e in episodes_out if e["verdict"] == "warning"]
    return {
        "episodes": episodes_out,
        "verdict": "failed" if failed_eps else "warning" if warning_eps else "passed",
        "summary": {
            "episodes": len(episodes_out),
            "training_ready_episodes": len(episodes_out) - len(bad_eps),
            "removed_episodes": len(bad_eps),
            "flagged_rows": total_flagged,
            "total_rows": len(rows),
        },
    }


# --------------------------------------------------------------------------
# 2. stream sync
# --------------------------------------------------------------------------

def check_stream_sync(streams: dict[str, list[float]],
                      tolerance_seconds: float = 0.05) -> dict[str, Any]:
    """Compare timestamp streams index-by-index against the first stream."""
    if not isinstance(streams, Mapping):
        raise ValueError("streams must be a mapping of names to timestamp lists")
    tolerance = _num(tolerance_seconds)
    if tolerance is None or tolerance < 0:
        raise ValueError("tolerance_seconds must be a finite non-negative number")

    cleaned: dict[str, list[float]] = {}
    for name, timestamps in streams.items():
        if not isinstance(name, str) or not name:
            raise ValueError("Stream names must be non-empty strings")
        if not isinstance(timestamps, Sequence) or isinstance(timestamps, (str, bytes)):
            raise ValueError(f"Stream '{name}' must contain a list of finite timestamps")
        values = []
        for index, timestamp in enumerate(timestamps):
            value = _num(timestamp)
            if value is None:
                raise ValueError(f"Stream '{name}' timestamp at index {index} must be finite and numeric")
            values.append(value)
        cleaned[name] = values

    names = list(cleaned)
    if len(names) < 2:
        return {"verdict": "passed", "in_sync": True, "streams": {},
                "detail": "Need at least two streams to compare."}
    reference_name = names[0]
    reference = cleaned[reference_name]
    compared: dict[str, Any] = {}
    all_in_sync = True
    for name in names[1:]:
        other = cleaned[name]
        n = min(len(reference), len(other))
        length_mismatch = len(other) != len(reference)
        if n == 0:
            compared[name] = {
                "median_offset_seconds": None,
                "jitter_seconds": None,
                "in_sync": False,
                "samples_compared": 0,
                "samples_in_stream": len(other),
                "samples_in_reference": len(reference),
                "length_mismatch": length_mismatch,
                "detail": "Stream is empty or the reference stream is empty.",
            }
            all_in_sync = False
            continue
        offsets = [other[i] - reference[i] for i in range(n)]
        median_offset = statistics.median(offsets)
        jitter = max(offsets) - min(offsets)
        # A shared prefix is insufficient: missing tail samples can shift
        # camera/state/action alignment in training data.
        in_sync = (abs(median_offset) <= tolerance
                   and jitter <= tolerance
                   and not length_mismatch)
        all_in_sync = all_in_sync and in_sync
        compared[name] = {
            "median_offset_seconds": median_offset,
            "jitter_seconds": jitter,
            "in_sync": in_sync,
            "samples_compared": n,
            "samples_in_stream": len(other),
            "samples_in_reference": len(reference),
            "length_mismatch": length_mismatch,
        }
    return {
        "verdict": "passed" if all_in_sync else "failed",
        "in_sync": all_in_sync,
        "reference_stream": reference_name,
        "tolerance_seconds": tolerance,
        "streams": compared,
    }


# --------------------------------------------------------------------------
# 3. action vs state
# --------------------------------------------------------------------------

def action_state_consistency(rows: list[dict[str, Any]],
                             action_col: str,
                             state_col: str,
                             tolerance: float = 0.0) -> dict[str, Any]:
    """Did the robot DO what the action said?

    For each step inside an episode: the recorded action at step i is the
    command (e.g. a joint velocity or a position delta). The actual state
    change from step i to step i+1 should at least move in the same
    DIRECTION (sign). If the action says "+" and the state moves "-"
    (both bigger than `tolerance`, so stillness/noise doesn't count),
    one of the two recordings is mislabelled or time-shifted — poison for
    training, because the AI learns the wrong cause and effect.

    Returns {"flagged_rows": [...], "count": n, "mismatches": [...]} where
    flagged_rows are positions in the original `rows` list (the step whose
    action disagrees with the movement that followed it).
    """
    tolerance_value = _num(tolerance)
    if tolerance_value is None or tolerance_value < 0:
        raise ValueError("tolerance must be a finite non-negative number")
    flagged: list[int] = []
    mismatches: list[dict[str, Any]] = []
    for _name, members in _group_episodes(rows):
        for pos in range(len(members) - 1):
            idx, row = members[pos]
            next_idx, next_row = members[pos + 1]
            action = _num(row.get(action_col))
            first = _num(row.get(state_col))
            last = _num(next_row.get(state_col))
            if action is None or first is None or last is None:
                continue
            change = last - first
            if abs(action) <= tolerance_value or abs(change) <= tolerance_value:
                continue
            if (action > 0) != (change > 0):
                flagged.append(idx)
                mismatches.append({
                    "row": idx,
                    "next_row": next_idx,
                    "action": action,
                    "state_change": change,
                })
    return {
        "verdict": "failed" if flagged else "passed",
        "flagged_rows": flagged,
        "count": len(flagged),
        "mismatches": mismatches,
    }


# --------------------------------------------------------------------------
# 4. clean export
# --------------------------------------------------------------------------

def export_clean_dataset(rows: list[dict[str, Any]],
                         robotics_limits: dict[str, tuple[float, float]] | None = None,
                         conditions: dict[str, float] | None = None
                         ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (clean_rows, report): `rows` with every FAILING EPISODE
    removed whole.

    Episodes are kept whole on purpose: cutting single rows out of an
    episode leaves silent time gaps in the middle of a movement, which is
    its own kind of bad training data. One bad row -> the whole episode
    stays out (it can be repaired and re-checked separately).

    report names each removed episode and its failure labels, so the
    removal is explainable, not silent.
    """
    quality = episode_quality(rows, robotics_limits, conditions)
    bad_ids = {e["episode_id"] for e in quality["episodes"] if not e["training_ready"]}
    key = _episode_key_name(rows)
    clean_rows = [
        row for row in rows
        if (str(_episode_value(row, key, "(missing episode)")) if key else "Episode 1") not in bad_ids
    ]
    report = {
        "kept_episodes": [e["episode_id"] for e in quality["episodes"]
                          if e["training_ready"]],
        "removed_episodes": [
            {"episode_id": e["episode_id"],
             "failure_labels": e["failure_labels"],
             "failed_checks": [c["name"] for c in e["failed_checks"]],
             "samples_removed": e["samples"]}
            for e in quality["episodes"] if not e["training_ready"]
        ],
        "rows_in": len(rows),
        "rows_out": len(clean_rows),
    }
    return clean_rows, report
