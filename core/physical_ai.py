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
    "action_state_causality",
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
    "actuator_chatter",      # high-frequency velocity oscillation (spectral power check)
    "energy_anomaly",        # kinetic-energy change no recorded effort can explain
    "foot_slip",             # loaded foot sliding (contact-solver slip)
    "timestamp_skew",        # camera/joint streams out of sync
    "workspace_floor_violation", # FK places the tip below the workspace floor
    "self_collision",        # link capsules closer than the clearance minimum
    "dead_episode",          # barely any motion for the whole episode
    "stall_torque",          # high torque while the joint does not move
)

EPISODE_KEYS = ("episode_id", "episode", "trajectory_id", "sequence_id")
TIME_KEYS = ("time", "t", "timestamp", "simulation_time", "sim_time", "elapsed_time")
MAX_STREAM_SYNC_SAMPLES = 1_000_000


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
    ("robotics_chatter", "actuator_chatter"),
    ("robotics_energy", "energy_anomaly"),
    ("robotics_foot_slip", "foot_slip"),
    ("robotics_stream_skew", "timestamp_skew"),
    ("robotics_workspace_floor", "workspace_floor_violation"),
    ("robotics_self_collision", "self_collision"),
)


def _dead_episode_label(ep_rows: list[dict[str, Any]],
                        min_active_motion_ratio: float) -> list[str]:
    """An episode where almost no joint position ever changes is dead weight:
    the policy produced nothing (or the recorder captured the wrong window),
    and training on it teaches the model to do nothing. A step is "active"
    when ANY joint position changes between consecutive samples; the episode
    is flagged when the active fraction drops below the configured ratio."""
    joint_cols = sorted({
        k for row in ep_rows for k, v in row.items()
        if k.startswith("joint") and k.endswith("_position") and _num(v) is not None
    })
    if not joint_cols:
        return []
    if len(ep_rows) < 2:
        return ["dead_episode"]  # a single sample cannot demonstrate motion
    active = 0
    for pos in range(len(ep_rows) - 1):
        for col in joint_cols:
            first = _num(ep_rows[pos].get(col))
            last = _num(ep_rows[pos + 1].get(col))
            if first is not None and last is not None and abs(last - first) > 1e-9:
                active += 1
                break
    if active / (len(ep_rows) - 1) < min_active_motion_ratio:
        return ["dead_episode"]
    return []


def _stall_torque_label(ep_rows: list[dict[str, Any]],
                        limits: dict[str, tuple[float, float]],
                        max_stall_duration_s: float,
                        stall_torque_fraction: float = 0.5) -> list[str]:
    """A joint holding high torque while its position does not move is
    stalled — pushing against an obstacle, a joint limit, or a wedged
    gripper. Flag when any torque/effort signal stays above
    `stall_torque_fraction` of its configured limit for more than
    `max_stall_duration_s` while the matching position signal is frozen."""
    time_key = next(
        (key for row in ep_rows for key in row
         if str(key).strip().lower() in TIME_KEYS),
        None,
    )
    if time_key is None:
        return []  # duration cannot be measured; base checks own time problems
    times = [_num(row.get(time_key)) for row in ep_rows]
    for column, (lo, hi) in limits.items():
        if "torque" not in column and "effort" not in column:
            continue
        position_column = column.replace("torque", "position").replace("effort", "position")
        if not any(position_column in row for row in ep_rows):
            continue
        threshold = stall_torque_fraction * max(abs(lo), abs(hi))
        run_start: int | None = None
        for pos in range(len(ep_rows)):
            torque = _num(ep_rows[pos].get(column))
            first = _num(ep_rows[pos].get(position_column))
            stalled = (
                torque is not None and abs(torque) >= threshold
                and first is not None
                and (pos == 0 or _num(ep_rows[pos - 1].get(position_column)) == first)
            )
            if stalled:
                if run_start is None:
                    run_start = pos
                continue
            if run_start is not None:
                end_time, start_time = times[pos], times[run_start]
                if end_time is not None and start_time is not None \
                        and end_time - start_time > max_stall_duration_s:
                    return ["stall_torque"]
                run_start = None
        if run_start is not None:
            end_time, start_time = times[-1], times[run_start]
            if end_time is not None and start_time is not None \
                    and end_time - start_time > max_stall_duration_s:
                return ["stall_torque"]
    return []


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
                    conditions: dict[str, float] | None = None,
                    min_active_motion_ratio: float | None = None,
                    max_stall_duration_s: float | None = None,
                    stall_torque_fraction: float = 0.5) -> dict[str, Any]:
    """Score every episode in `rows`.

    rows: one dict per sample, like the rest of SimAPI:
          {"episode_id": "pick_cup_01", "time": 0.02,
           "joint_1_position": 0.02, "joint_1_velocity": 1.0, ...}
    robotics_limits: allowed (min, max) per signal, the robot's own limits.
    conditions: passed through to the base checker (max_time_step,
          velocity_tolerance, acceleration_tolerance).
    min_active_motion_ratio: opt-in dead-episode filter; flag episodes whose
          fraction of motion-active steps (any joint position changing)
          falls below this ratio in [0, 1].
    max_stall_duration_s: opt-in stall filter; flag episodes where a torque
          signal holds at least `stall_torque_fraction` of its configured
          limit for longer than this duration while its joint is frozen.
    stall_torque_fraction: fraction of the configured torque limit that
          counts as "high torque" for the stall check (default 0.5).

    Returns {"episodes": [...], "verdict": ..., "summary": {...}} where each
    episode entry has: episode_id, samples, verdict, failure_labels,
    flagged_rows (positions in the original `rows` list), failed_checks,
    training_ready.
    """
    if min_active_motion_ratio is not None and not 0 <= min_active_motion_ratio <= 1:
        raise ValueError("min_active_motion_ratio must be between 0 and 1")
    if max_stall_duration_s is not None and max_stall_duration_s <= 0:
        raise ValueError("max_stall_duration_s must be a positive duration in seconds")
    if not 0 < stall_torque_fraction <= 1:
        raise ValueError("stall_torque_fraction must be in (0, 1]")
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
        extra_labels = _torque_saturation_labels(ep_rows, limits) + _frozen_sensor_labels(ep_rows)
        if min_active_motion_ratio is not None:
            extra_labels += _dead_episode_label(ep_rows, min_active_motion_ratio)
        if max_stall_duration_s is not None:
            extra_labels += _stall_torque_label(
                ep_rows, limits, max_stall_duration_s, stall_torque_fraction
            )
        for extra in extra_labels:
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
        return {"verdict": "insufficient_data", "in_sync": False, "streams": {},
                "detail": "Need at least two streams to compare."}
    if len(names) > 32:
        raise ValueError("At most 32 streams can be synchronized in one request")
    sample_count = sum(len(values) for values in cleaned.values())
    if sample_count > MAX_STREAM_SYNC_SAMPLES:
        raise ValueError(
            f"Stream synchronization is limited to {MAX_STREAM_SYNC_SAMPLES} timestamps per request"
        )
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
# 3b. action -> state causality and frame-shift (lag) detection
# --------------------------------------------------------------------------

def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    var_x = sum(d * d for d in dx)
    var_y = sum(d * d for d in dy)
    if var_x <= 0.0 or var_y <= 0.0:
        return None
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / math.sqrt(var_x * var_y)


def action_state_causality(rows: list[dict[str, Any]],
                           action_col: str,
                           state_col: str,
                           max_lag: int = 3,
                           min_correlation: float = 0.1,
                           lag_margin: float = 0.02) -> dict[str, Any]:
    """Does `action[t]` positively correlate with the velocity change that
    follows it — and does it do so at lag 1?

    For each candidate lag L in 1..max_lag the Pearson correlation between
    action[t] and the delayed velocity change
    Δv[t+L] = state[t+L] - 2*state[t+L-1] + state[t+L-2] is computed inside
    each episode. A healthy recording peaks at lag 1 (the command moves the
    very next step). Two failure modes are reported:

      * no_causality  — no lag reaches `min_correlation`: the recorded
        actions have no measurable effect on the state (mislabeled channels,
        or the action column is not what it claims to be).
      * lag_mismatch  — the best correlation sits at a lag other than 1 and
        beats the lag-1 correlation by more than `lag_margin`: the streams
        are shifted by (best_lag - 1) frames, the classic off-by-one
        recorder bug that teaches a model the wrong cause and effect.

    Returns {"verdict", "reason", "best_lag", "correlations_by_lag",
    "flagged_rows", "count"}; flagged rows list the steps whose action
    sign disagrees with the state change at the best lag (only when a
    best lag exists).
    """
    if max_lag < 1:
        raise ValueError("max_lag must be at least 1")
    if not 0 <= min_correlation <= 1:
        raise ValueError("min_correlation must be between 0 and 1")

    actions: dict[int, float] = {}
    states: dict[int, float] = {}
    for index, row in enumerate(rows):
        action = _num(row.get(action_col))
        state = _num(row.get(state_col))
        if action is not None:
            actions[index] = action
        if state is not None:
            states[index] = state

    pairs_by_lag: dict[int, list[tuple[float, float]]] = {lag: [] for lag in range(1, max_lag + 1)}
    for _name, members in _group_episodes(rows):
        positions = [idx for idx, _row in members if idx in states and idx in actions]
        if len(positions) < 4:
            continue
        local = {idx: pos for pos, idx in enumerate(positions)}
        for lag in range(1, max_lag + 1):
            for idx in positions:
                target = local[idx] + lag
                if target >= len(positions) or local[idx] + lag - 2 < 0:
                    continue
                i1, i2, i3 = (positions[local[idx] + lag],
                              positions[local[idx] + lag - 1],
                              positions[local[idx] + lag - 2])
                if i2 not in states or i3 not in states:
                    continue
                delta_v = states[i1] - 2.0 * states[i2] + states[i3]
                pairs_by_lag[lag].append((actions[idx], delta_v))

    correlations: dict[int, float | None] = {}
    for lag in range(1, max_lag + 1):
        pairs = pairs_by_lag[lag]
        correlations[lag] = _pearson([a for a, _d in pairs], [d for _a, d in pairs]) if pairs else None

    evaluated = {lag: value for lag, value in correlations.items() if value is not None}
    if not evaluated:
        return {
            "verdict": "warning",
            "reason": "insufficient_data",
            "best_lag": None,
            "correlations_by_lag": correlations,
            "flagged_rows": [],
            "count": 0,
            "detail": (
                "Action/state causality could not be evaluated: fewer than four aligned "
                "action and state samples per episode."
            ),
        }

    best_lag = max(evaluated, key=lambda lag: evaluated[lag])  # type: ignore[arg-type]
    best_value = evaluated[best_lag]
    if best_value < min_correlation:
        verdict, reason = "failed", "no_causality"
        detail = (
            f"No lag in 1..{max_lag} correlates {action_col} with the following "
            f"{state_col} velocity change above {min_correlation:g} (best: {best_value:.3f} at lag {best_lag})."
        )
    elif best_lag != 1 and best_value > (evaluated.get(1) or -1.0) + lag_margin:
        verdict, reason = "failed", "lag_mismatch"
        detail = (
            f"{action_col} tracks the {state_col} velocity change best at lag {best_lag} "
            f"(r={best_value:.3f}), not lag 1 (r={evaluated.get(1, float('nan')):.3f}): the streams "
            f"are shifted by {best_lag - 1} frame(s)."
        )
    else:
        verdict, reason = "passed", "causal_at_lag_1" if best_lag == 1 else "causal"
        detail = (
            f"{action_col} correlates with the following {state_col} velocity change at lag "
            f"{best_lag} (r={best_value:.3f})."
        )

    flagged: list[int] = []
    if verdict != "failed" and best_lag is not None:
        for idx, _pair in _causality_flagged_rows(
            rows, _group_episodes(rows), action_col, state_col, best_lag
        ):
            flagged.append(idx)

    return {
        "verdict": verdict,
        "reason": reason,
        "best_lag": best_lag,
        "correlations_by_lag": correlations,
        "flagged_rows": flagged,
        "count": len(flagged),
        "detail": detail,
    }


def _causality_flagged_rows(rows, groups, action_col, state_col, lag):
    """Steps whose action sign disagrees with the delayed velocity change."""
    for _name, members in groups:
        aligned = [
            (idx, _num(row.get(action_col)), _num(row.get(state_col)))
            for idx, row in members
            if _num(row.get(action_col)) is not None and _num(row.get(state_col)) is not None
        ]
        for pos in range(len(aligned) - lag):
            first_pos = pos + lag - 2
            if first_pos < 0:
                continue
            idx, action, _state = aligned[pos]
            s1 = aligned[pos + lag][2]
            s2 = aligned[pos + lag - 1][2]
            s3 = aligned[first_pos][2]
            delta_v = s1 - 2.0 * s2 + s3
            if abs(action) > 1e-9 and abs(delta_v) > 1e-9 and (action > 0) != (delta_v > 0):
                yield idx, (action, delta_v)


# --------------------------------------------------------------------------
# 4. clean export
# --------------------------------------------------------------------------

def export_clean_dataset(rows: list[dict[str, Any]],
                         robotics_limits: dict[str, tuple[float, float]] | None = None,
                         conditions: dict[str, float] | None = None,
                         min_active_motion_ratio: float | None = None,
                         max_stall_duration_s: float | None = None,
                         stall_torque_fraction: float = 0.5
                         ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (clean_rows, report): `rows` with every FAILING EPISODE
    removed whole.

    Episodes are kept whole on purpose: cutting single rows out of an
    episode leaves silent time gaps in the middle of a movement, which is
    its own kind of bad training data. One bad row -> the whole episode
    stays out (it can be repaired and re-checked separately).

    The optional dead-episode (min_active_motion_ratio) and stall-torque
    (max_stall_duration_s) filters pass through to episode_quality; every
    failure tag they produce flows into the removal report below.

    report names each removed episode and its failure labels, so the
    removal is explainable, not silent.
    """
    quality = episode_quality(
        rows, robotics_limits, conditions,
        min_active_motion_ratio=min_active_motion_ratio,
        max_stall_duration_s=max_stall_duration_s,
        stall_torque_fraction=stall_torque_fraction,
    )
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
