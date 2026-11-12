"""
physical_ai_v2.py — second layer of quality tools for Physical AI data.

Drop this file into the SimAPI repo at:  core/physical_ai_v2.py
(it sits next to core/physical_ai.py and builds on the same checker,
core/robotics_validation.check_robotics_limits — it replaces nothing).

Physical AI = AI that learns to move real robots. It trains on
*episodes* (one full attempt at a task). This file exists because of
one embarrassing problem and a handful of useful extras:

  THE PROBLEM — generic defaults are not robot limits
  A generic screening range cannot prove that data fits a particular
  robot. This file does not replace the core defaults. Instead it
  offers named screening profiles and a guarded call path:

    validate_guarded(...)  If you give no limits and no profile, it
        applies a generic screening profile instead of silently
        presenting built-in defaults as robot-specific, stamps the
        result with a "profile_guard" warning, and says
        training_ready=False.

  THE EXTRAS
    ARM_PROFILES / get_profile(...)   Ready-made realistic limits for
        common arms (Franka Panda, UR5e, UR10e, xArm 7, SO-101, and a
        generic lab arm). "Profile" = a named set of allowed ranges.
    check_jerk(...)        "Jerk" = how fast acceleration itself
        changes. A sudden jerk spike usually means a glitch, a hit,
        or a logging error — smooth real motors don't teleport
        their acceleration.
    detect_units(...)      Catches the classic degrees-vs-radians
        mix-up (data recorded in degrees, limits written in radians),
        plus convert_degrees_to_radians(...) to fix the rows.
    dataset_health_score(...)  One 0-100 score for a whole dataset,
        with the top reasons dragging it down.
    cluster_failures(...)  Groups hundreds of failures into a short
        list of "these 200 are all the same problem".
    torque_saturation_trend(...)  Is the motor spending more and
        more time pinned near its limit as the episode goes on?
        That is a motor straining (or dying slowly).

Words used below:
  - "signal"  = one measured column, e.g. joint_1_position.
  - "torque"  = how hard a motor pushes, in Nm (also "effort" in ROS).
  - "screening profile" = realistic-but-generic limits used to catch
    nonsense. NOT a substitute for the robot's own URDF/datasheet.

Only dependency beyond the standard library: pandas + SimAPI's own
core/robotics_validation.py (same as physical_ai.py).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import pandas as pd

try:  # normal case: this file lives in simapi/core/
    from core.robotics_trajectory import normalize
    from core.robotics_validation import DEFAULT_ROBOTICS_LIMITS, check_robotics_limits
except ImportError:  # imported as a sibling module inside core/
    from robotics_trajectory import normalize
    from robotics_validation import DEFAULT_ROBOTICS_LIMITS, check_robotics_limits

__all__ = [
    "ARM_PROFILES",
    "GENERIC_PROFILE_NAME",
    "get_profile",
    "validate_guarded",
    "check_jerk",
    "detect_units",
    "convert_degrees_to_radians",
    "dataset_health_score",
    "cluster_failures",
    "torque_saturation_trend",
]

EPISODE_KEYS = ("episode_id", "episode", "trajectory_id", "sequence_id")
TIME_KEYS = ("time", "t", "timestamp", "simulation_time", "sim_time",
             "elapsed_time")

TWO_PI = 2 * math.pi


# ---------------------------------------------------------------------------
# helpers (same conventions as physical_ai.py / the repo trajectory engine)
# ---------------------------------------------------------------------------

def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _clean_limits(limits: dict | None, source: str = "limits") -> dict[str, tuple[float, float]]:
    """Validate a limits dict early, with a human-readable error naming
    the signal — same behaviour as physical_ai.py's _clean_limits."""
    if limits is not None and not isinstance(limits, Mapping):
        raise ValueError(f"{source} must map signal names to [min, max] pairs")
    cleaned: dict[str, tuple[float, float]] = {}
    for name, rng in (limits or {}).items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{source} signal names must be non-empty strings")
        if isinstance(rng, (str, bytes)):
            raise ValueError(
                f"{source}[{name!r}] must be a [min, max] pair of finite numbers, got {rng!r}"
            )
        try:
            lo, hi = rng
            pair = (_num(lo), _num(hi))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{source}[{name!r}] must be a [min, max] pair of "
                f"numbers, got {rng!r}"
            ) from exc
        if pair[0] is None or pair[1] is None:
            raise ValueError(
                f"{source}[{name!r}] must contain finite numeric bounds, got {rng!r}"
            )
        if pair[0] >= pair[1]:
            raise ValueError(
                f"{source}[{name!r}] minimum must be less than maximum: {rng!r}"
            )
        cleaned[name] = (pair[0], pair[1])
    return cleaned


def _episode_key_name(rows: list[dict[str, Any]]) -> str | None:
    for key in EPISODE_KEYS:
        if any(key in row for row in rows):
            return key
    return None


def _group_episodes(rows: list[dict[str, Any]]):
    """Yield (episode_id, [(global_index, row), ...]) in first-seen order."""
    key = _episode_key_name(rows)
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    order: list[str] = []
    for idx, row in enumerate(rows):
        name = str(row.get(key, "(missing episode)")) if key else "Episode 1"
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append((idx, row))
    return [(name, groups[name]) for name in order]


def _time_key_name(rows: list[dict[str, Any]]) -> str | None:
    for key in TIME_KEYS:
        if any(key in row for row in rows):
            return key
    return None


def _joint_indices(rows: list[dict[str, Any]]) -> list[int]:
    """Joint numbers present in joint_<i>_<signal> columns, sorted."""
    found: set[int] = set()
    for row in rows:
        for col in row:
            parts = str(col).split("_")
            if len(parts) >= 3 and parts[0] == "joint" and parts[1].isdigit():
                found.add(int(parts[1]))
    return sorted(found)


# ---------------------------------------------------------------------------
# 1. robot arm profiles — realistic screening limits, NOT datasheet truth
# ---------------------------------------------------------------------------
# Each profile gives a fallback (min, max) per quantity. `joint_limits`
# overrides that fallback for specific joints where manufacturer data is
# available. Values remain screening bounds and must be checked against the
# exact robot generation, controller configuration, and URDF.
#   franka_panda — joint-specific torque, position, speed, acceleration.
#   ur5e         — 150 Nm shoulder/base, 28 Nm wrist joints.
#   ur10e        — 330 Nm base/shoulder, 150 Nm elbow, 56 Nm wrists.
#   xarm7        — position ranges and torque values for xArm 7 generation
#                  1304 and earlier; verify the serial/model generation.
#   so101        — the small LeRobot servo arm (Feetech STS3215 servos,
#                  ~3 Nm stall torque) — limits are FAR lower on purpose.
#   generic_lab_arm — the guard's fallback: torque ±150, vel ±3.0,
#                  accel ±25, position ±2π.
# Profile references for the per-joint overrides below:
#   Franka FCI robot specifications: https://frankarobotics.github.io/docs/robot_specifications.html
#   Universal Robots max joint torque table: https://www.universal-robots.com/articles/ur/robot-care-maintenance/max-joint-torques-cb3-and-e-series/
#   Universal Robots UR5e tech sheet: https://www.universal-robots.com/manuals/EN/TechSheets/UR5e_techsheet_pdf_online/UR5e_techsheet_en.pdf
#   UFACTORY joint parameters: https://docs.supportarticle.ufactory.cc/support_articles/hardware/ufactory-joint-parameters.html
#   UFACTORY xArm 7 tech manual: https://www.ufactory.cc/wp-content/uploads/2024/01/xArm-User-Manual-V2.3.0.pdf
# EVERY profile is a STARTING screening profile. Verify against the
# robot's own URDF / datasheet before trusting a pass.

ARM_PROFILES: dict[str, dict[str, Any]] = {
    "franka_panda": {
        "description": "Franka Emika Panda, 7 joints, joint-specific screening bounds.",
        "default_joints": 7,
        "limits": {
            "position": (-2.9, 2.9),
            "velocity": (-2.175, 2.175),
            "acceleration": (-15.0, 15.0),
            "torque": (-87.0, 87.0),
        },
        "joint_limits": {
            1: {"position": (-2.8973, 2.8973), "velocity": (-2.175, 2.175),
                "acceleration": (-15.0, 15.0), "torque": (-87.0, 87.0)},
            2: {"position": (-1.7628, 1.7628), "velocity": (-2.175, 2.175),
                "acceleration": (-7.5, 7.5), "torque": (-87.0, 87.0)},
            3: {"position": (-2.8973, 2.8973), "velocity": (-2.175, 2.175),
                "acceleration": (-10.0, 10.0), "torque": (-87.0, 87.0)},
            4: {"position": (-3.0718, -0.0698), "velocity": (-2.175, 2.175),
                "acceleration": (-12.5, 12.5), "torque": (-87.0, 87.0)},
            5: {"position": (-2.8973, 2.8973), "velocity": (-2.610, 2.610),
                "acceleration": (-15.0, 15.0), "torque": (-12.0, 12.0)},
            6: {"position": (-0.0175, 3.7525), "velocity": (-2.610, 2.610),
                "acceleration": (-20.0, 20.0), "torque": (-12.0, 12.0)},
            7: {"position": (-2.8973, 2.8973), "velocity": (-2.610, 2.610),
                "acceleration": (-20.0, 20.0), "torque": (-12.0, 12.0)},
        },
    },
    "ur5e": {
        "description": "Universal Robots UR5e, 6 joints, 28 Nm wrist and 150 Nm arm-joint bounds.",
        "default_joints": 6,
        "limits": {
            "position": (-TWO_PI, TWO_PI),
            "velocity": (-3.14, 3.14),
            "acceleration": (-25.0, 25.0),
            "torque": (-150.0, 150.0),
        },
        "joint_limits": {
            4: {"torque": (-28.0, 28.0)},
            5: {"torque": (-28.0, 28.0)},
            6: {"torque": (-28.0, 28.0)},
        },
    },
    "ur10e": {
        "description": "Universal Robots UR10e, 6 joints, larger (330 Nm base class).",
        "default_joints": 6,
        "limits": {
            "position": (-TWO_PI, TWO_PI),
            "velocity": (-3.14, 3.14),
            "acceleration": (-25.0, 25.0),
            "torque": (-330.0, 330.0),
        },
        "joint_limits": {
            3: {"torque": (-150.0, 150.0)},
            4: {"torque": (-56.0, 56.0)},
            5: {"torque": (-56.0, 56.0)},
            6: {"torque": (-56.0, 56.0)},
        },
    },
    "xarm7": {
        "description": "UFACTORY xArm 7 screening bounds (verify hardware generation).",
        "default_joints": 7,
        "limits": {
            "position": (-TWO_PI, TWO_PI),
            "velocity": (-3.0, 3.0),
            "acceleration": (-25.0, 25.0),
            "torque": (-80.0, 80.0),
        },
        "joint_limits": {
            1: {"position": (-TWO_PI, TWO_PI), "torque": (-163.2, 163.2)},
            2: {"position": (-2.059, 2.0944), "torque": (-163.2, 163.2)},
            3: {"position": (-TWO_PI, TWO_PI), "torque": (-81.6, 81.6)},
            4: {"position": (-0.19198, 3.927), "torque": (-81.6, 81.6)},
            5: {"position": (-TWO_PI, TWO_PI), "torque": (-81.6, 81.6)},
            6: {"position": (-1.69297, math.pi), "torque": (-30.6, 30.6)},
            7: {"position": (-TWO_PI, TWO_PI), "torque": (-30.6, 30.6)},
        },
    },
    "so101": {
        "description": "SO-101 LeRobot servo arm (STS3215 servos, ~3 Nm stall). Small and weak — on purpose.",
        "default_joints": 6,
        "limits": {
            "position": (-math.pi, math.pi),
            "velocity": (-4.0, 4.0),
            "acceleration": (-30.0, 30.0),
            "torque": (-3.0, 3.0),
        },
    },
    "generic_lab_arm": {
        "description": "Generic lab robot arm screening profile (the guard fallback).",
        "default_joints": 6,
        "limits": {
            "position": (-TWO_PI, TWO_PI),
            "velocity": (-3.0, 3.0),
            "acceleration": (-25.0, 25.0),
            "torque": (-150.0, 150.0),
        },
    },
}

GENERIC_PROFILE_NAME = "generic_lab_arm"


def get_profile(name: str, num_joints: int | None = None) -> dict[str, tuple[float, float]]:
    """Expand a named arm profile to per-joint limit keys.

    get_profile("ur5e", 6) ->
        {"joint_1_position": (-2π, 2π), "joint_1_velocity": (-3.14, 3.14),
         "joint_1_torque": (-150, 150), ..., "joint_6_torque": ...}

    num_joints=None uses the profile's own joint count. Raises
    ValueError naming the bad name and listing the known profiles.
    """
    key = str(name).strip().lower()
    if key not in ARM_PROFILES:
        raise ValueError(
            f"Unknown arm profile {name!r}. Known profiles: "
            f"{', '.join(sorted(ARM_PROFILES))}"
        )
    profile = ARM_PROFILES[key]
    if num_joints is None:
        count = int(profile["default_joints"])
    else:
        if isinstance(num_joints, bool):
            raise ValueError("num_joints must be a positive integer")
        try:
            count = int(num_joints)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("num_joints must be a positive integer") from exc
        if count != num_joints or count <= 0:
            raise ValueError("num_joints must be a positive integer")
    out: dict[str, tuple[float, float]] = {}
    for i in range(1, count + 1):
        joint_limits = profile.get("joint_limits", {}).get(i, {})
        for quantity, fallback in profile["limits"].items():
            bounds = joint_limits.get(quantity, fallback)
            out[f"joint_{i}_{quantity}"] = (float(bounds[0]), float(bounds[1]))
    return out


def _profile_limits_for_rows(profile_name: str, rows: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    """Profile limits sized to the joints actually present in `rows`,
    plus the generic quantity keys (joint_torque etc.) so recordings
    that use un-numbered column names are guarded too.

    IMPORTANT: only keys whose column is actually present in the data
    are returned. The core engine fails closed on a *configured* limit
    whose column is missing — correct for a user's own limits, wrong
    for a profile: a 1-joint log must not fail for joints 2-6 that it
    simply doesn't record."""
    present = {str(col) for row in rows for col in row}
    profile_key = str(profile_name).strip().lower()
    if profile_key not in ARM_PROFILES:
        raise ValueError(
            f"Unknown arm profile {profile_name!r}. Known profiles: "
            f"{', '.join(sorted(ARM_PROFILES))}"
        )
    profile = ARM_PROFILES[profile_key]
    limits: dict[str, tuple[float, float]] = {}
    indices = _joint_indices(rows)
    if indices:
        for i in indices:
            if i <= 0 or (
                profile_key != GENERIC_PROFILE_NAME
                and i > int(profile["default_joints"])
            ):
                continue
            joint_limits = profile.get("joint_limits", {}).get(i, {})
            for quantity, fallback in profile["limits"].items():
                bounds = joint_limits.get(quantity, fallback)
                signal_name = f"joint_{i}_{quantity}"
                if signal_name in present:
                    limits[signal_name] = (float(bounds[0]), float(bounds[1]))
                if quantity == "torque":
                    effort_key = f"joint_{i}_effort"
                    if effort_key in present:
                        limits[effort_key] = (float(bounds[0]), float(bounds[1]))

    # The generic profile is a broad screening guard, so its bounds must
    # cover every joint signal the core recognizes, including named joints
    # and numbered joints beyond the profile's nominal six-joint example.
    if profile_key == GENERIC_PROFILE_NAME:
        for raw_name in present:
            name = normalize(raw_name)
            if not name.startswith("joint"):
                continue
            quantity = next(
                (q for q in ("position", "velocity", "acceleration", "torque", "effort")
                 if name.endswith("_" + q)),
                None,
            )
            if quantity is None:
                continue
            profile_quantity = "torque" if quantity == "effort" else quantity
            bounds = profile["limits"].get(profile_quantity)
            if bounds is not None:
                limits[name] = (float(bounds[0]), float(bounds[1]))

    for quantity, bounds in profile["limits"].items():
        keys = [f"joint_{quantity}"]
        if quantity == "torque":
            keys.append("joint_effort")
        for signal_name in keys:
            if signal_name in present:
                limits[signal_name] = (float(bounds[0]), float(bounds[1]))
    return limits


def _core_defaulted_signals(
    rows: list[dict[str, Any]], configured_limits: dict[str, tuple[float, float]]
) -> list[str]:
    """List known robot signals that the core would check with broad defaults.

    A profile or a partial explicit limits mapping must not make the other
    recognized signals appear robot-specific when the engine still falls back
    to its broad defaults for them.
    """
    configured = {normalize(name) for name in configured_limits}
    for name in tuple(configured):
        if name.endswith("_effort"):
            configured.add(name.removesuffix("_effort") + "_torque")
        elif name.endswith("_torque"):
            configured.add(name.removesuffix("_torque") + "_effort")

    joint_quantities = ("position", "velocity", "acceleration", "torque", "effort")
    uncovered: set[str] = set()
    for row in rows:
        for raw_name in row:
            name = normalize(str(raw_name))
            recognized = name in DEFAULT_ROBOTICS_LIMITS or (
                name.startswith("joint")
                and any(name.endswith("_" + quantity) for quantity in joint_quantities)
            )
            if not recognized:
                continue
            if name in configured:
                continue
            if name.endswith("_effort") and name.removesuffix("_effort") + "_torque" in configured:
                continue
            if name.endswith("_torque") and name.removesuffix("_torque") + "_effort" in configured:
                continue
            uncovered.add(str(raw_name))
    return sorted(uncovered)


# ---------------------------------------------------------------------------
# 2. validate_guarded — the 100k-defaults guard
# ---------------------------------------------------------------------------

def validate_guarded(rows: list[dict[str, Any]],
                     limits: dict[str, tuple[float, float]] | None = None,
                     profile: str | None = None,
                     allow_defaults: bool = False,
                     conditions: dict[str, float] | None = None) -> dict[str, Any]:
    """check_robotics_limits with an honesty guard on top.

    - Caller passes explicit `limits` and/or a `profile` name: those
      are used (explicit limits win on conflicts). Normal result.
    - Caller passes NEITHER and allow_defaults is False: built-in
      screening defaults are NOT presented as robot-specific. The
      check runs with the generic_lab_arm screening profile instead, a
      "profile_guard" warning check is added, verdict is capped at
      "warning" (never a clean "passed"), training_ready is False.
    - allow_defaults=True: the raw core behaviour runs, but a
      "profile_guard" warning still records that the
      result used screening defaults — and training_ready is False,
      because defaults prove nothing about YOUR robot.
    - Empty rows fail closed: verdict "failed", a "no_data" check.

    Returns the core report shape (checks / excluded / summary /
    evidence) PLUS: verdict, training_ready, limits_used,
    limits_source ("explicit" / "profile" / "profile+explicit" /
    "screening_profile" / "core_defaults"), profile_used.
    """
    explicit = _clean_limits(limits, source="limits")
    profile_name = str(profile).strip().lower() if profile is not None else None
    if profile_name is not None and profile_name not in ARM_PROFILES:
        raise ValueError(
            f"Unknown arm profile {profile!r}. Known profiles: "
            f"{', '.join(sorted(ARM_PROFILES))}"
        )
    if not rows:
        return {
            "verdict": "failed",
            "training_ready": False,
            "checks": [{
                "name": "no_data", "column": None, "status": "failed",
                "violations": 0,
                "detail": "No rows provided — nothing to validate.",
            }],
            "excluded": {},
            "summary": {},
            "evidence": {},
            "limits_used": explicit,
            "limits_source": "none",
            "profile_used": profile,
            "detail": "No rows provided — nothing to validate.",
        }

    guard_check: dict[str, Any] | None = None
    if profile_name is not None:
        profile_limits = _profile_limits_for_rows(profile_name, rows)
        effective = dict(profile_limits)
        effective.update(explicit)  # caller's own numbers win
        limits_source = "profile" if not explicit else "profile+explicit"
        profile_used: str | None = profile_name
        if profile_name == GENERIC_PROFILE_NAME:
            guard_check = {
                "name": "profile_guard", "column": None, "status": "warning",
                "violations": 0,
                "detail": (
                    "Profile 'generic_lab_arm' supplies screening-only bounds, "
                    "not limits for a specific robot. Verify the robot's "
                    "URDF or datasheet and supply robot-specific limits before "
                    "treating this data as training-ready."
                ),
            }
        elif not profile_limits:
            guard_check = {
                "name": "profile_guard", "column": None, "status": "warning",
                "violations": 0,
                "detail": (
                    f"Profile {profile_name!r} did not match any robot signals "
                    "in this recording. Core defaults may have been used; "
                    "this result is not evidence of robot-specific limits."
                ),
            }
    elif explicit:
        effective = dict(explicit)
        limits_source = "explicit"
        profile_used = None
    elif allow_defaults:
        effective = {}
        limits_source = "core_defaults"
        profile_used = None
        guard_check = {
            "name": "profile_guard", "column": None, "status": "warning",
            "violations": 0,
            "detail": (
                "allow_defaults=True: this run used SimAPI core's built-in "
                "screening defaults. Those defaults are not robot-specific "
                "limits and do not prove that the data fits a real robot. "
                "Pass limits= or profile= for a robot-specific check."
            ),
        }
    else:
        effective = _profile_limits_for_rows(GENERIC_PROFILE_NAME, rows)
        limits_source = "screening_profile"
        profile_used = GENERIC_PROFILE_NAME
        guard_check = {
            "name": "profile_guard", "column": None, "status": "warning",
            "violations": 0,
            "detail": (
                "No limits or profile were supplied, so built-in screening "
                "defaults were replaced with the generic_lab_arm profile "
                "(torque ±150 Nm, velocity ±3.0 rad/s, acceleration "
                "±25 rad/s², position ±2π). This result is SCREENING-ONLY: "
                "supply your robot's real profile or URDF limits for a "
                "verdict you can train on."
            ),
        }

    if limits_source in {"profile", "profile+explicit", "explicit"}:
        unprofiled_signals = _core_defaulted_signals(rows, effective)
        if unprofiled_signals:
            detail = (
                "These robot signals are still checked only with SimAPI core "
                "defaults, not robot-specific bounds: "
                + ", ".join(unprofiled_signals)
                + ". Supply limits for them before treating a pass as training-ready."
            )
            if guard_check is None:
                guard_check = {
                    "name": "profile_guard", "column": None, "status": "warning",
                    "violations": 0, "detail": detail,
                }
            else:
                guard_check["detail"] += " " + detail

    report = check_robotics_limits(
        pd.DataFrame(rows), effective or None,
        source_rows=rows, conditions=conditions,
    )
    checks = list(report.get("checks", []))
    if guard_check is not None:
        checks.append(guard_check)
    excluded = report.get("excluded") or {}

    statuses = {c.get("status") for c in checks}
    if "failed" in statuses:
        verdict = "failed"
    elif "warning" in statuses:
        verdict = "warning"
    else:
        verdict = "passed"
    training_ready = verdict == "passed" and not excluded and guard_check is None

    return {
        "verdict": verdict,
        "training_ready": training_ready,
        "checks": checks,
        "excluded": excluded,
        "summary": report.get("summary", {}),
        "evidence": report.get("evidence", {}),
        "limits_used": effective,
        "limits_source": limits_source,
        "profile_used": profile_used,
    }


# ---------------------------------------------------------------------------
# 3. jerk checks
# ---------------------------------------------------------------------------

def _derivative_series(times: list[float], values: list[float]):
    """Finite differences: returns (end_indices, rates) where rates[k]
    is (values[end]-values[start]) / dt over one step. Steps with
    dt <= 0 or missing values are skipped."""
    ends: list[int] = []
    rates: list[float] = []
    for i in range(1, len(values)):
        dt = times[i] - times[i - 1]
        if dt <= 0:
            continue
        ends.append(i)
        rates.append((values[i] - values[i - 1]) / dt)
    return ends, rates


def check_jerk(rows: list[dict[str, Any]],
               max_jerk: float = 500.0) -> dict[str, Any]:
    """Flag rows where jerk (change of acceleration per second) spikes.

    Chain per joint, per episode: position -> velocity -> acceleration
    -> jerk, each step a finite difference over the recorded timestamps
    (same time/episode column conventions as the repo's trajectory
    engine). If a joint has a recorded velocity column but no position
    column, the chain starts at velocity. Jerk is attributed to the
    LAST row of the three-step window that produced it.

    max_jerk is in rad/s³ for position-based chains. 500 is a loose
    screening default — real arms move far smoother; tighten it with
    your robot's profile if you know better.

    Returns {"checks": [...SimAPI-shaped...], "excluded": {...},
             "flagged_rows": [...], "verdict": ...}.
    """
    limit_value = _num(max_jerk)
    if limit_value is None or limit_value <= 0:
        raise ValueError("max_jerk must be a finite positive number")
    limit = limit_value
    checks: list[dict[str, Any]] = []
    excluded: dict[int, list[str]] = {}
    time_key = _time_key_name(rows)
    if not rows or time_key is None:
        checks.append({
            "name": "robotics_jerk", "column": time_key, "status": "warning",
            "violations": 0, "indices": [], "low": -limit, "high": limit,
            "detail": "Not evaluated. No numeric time column: jerk needs timestamps.",
        })
        return {"checks": checks, "excluded": {}, "flagged_rows": [],
                "verdict": "warning"}

    # joint base -> {"position": col, "velocity": col} across all rows
    joints: dict[str, dict[str, str]] = {}
    for row in rows:
        for col in row:
            parts = str(col).split("_")
            if len(parts) >= 3 and parts[0] == "joint" and parts[-1] in ("position", "velocity"):
                base = "_".join(parts[:-1])
                joints.setdefault(base, {})[parts[-1]] = str(col)

    for base in sorted(joints):
        cols = joints[base]
        start_col = cols.get("position") or cols.get("velocity")
        assert start_col is not None
        for _ep, members in _group_episodes(rows):
            times = [_num(r.get(time_key)) for _, r in members]
            values = [_num(r.get(start_col)) for _, r in members]
            if any(t is None for t in times) or any(v is None for v in values):
                checks.append({
                    "name": f"robotics_jerk:{base}", "column": start_col,
                    "status": "warning", "violations": 0, "indices": [],
                    "low": -limit, "high": limit,
                    "detail": (
                        f"Not evaluated for episode {_ep!r}: timestamps or "
                        f"{start_col} contain missing, boolean, or non-finite values."
                    ),
                })
                continue
            t_list = [float(t) for t in times if t is not None]
            v_list = [float(v) for v in values if v is not None]
            if any(right <= left for left, right in zip(t_list, t_list[1:], strict=False)):
                checks.append({
                    "name": f"robotics_jerk:{base}", "column": start_col,
                    "status": "warning", "violations": 0, "indices": [],
                    "low": -limit, "high": limit,
                    "detail": (
                        f"Not evaluated for episode {_ep!r}: timestamps are "
                        "not strictly increasing. Check time-order findings first."
                    ),
                })
                continue
            # step 1 -> velocity series (ends at member positions e1)
            e1, vel = _derivative_series(t_list, v_list)
            if start_col.endswith("_velocity"):
                # recorded velocity IS the first series; differentiate once
                # for acceleration, once more for jerk — same code path if
                # we treat the raw series as "step 0":
                e1, vel = list(range(len(v_list))), list(v_list)
            if len(vel) < 3:
                continue
            # step 2 -> acceleration: difference of velocity over the
            # time between the ENDS of the velocity intervals.
            t_vel = [t_list[i] for i in e1]
            e2, acc = _derivative_series(t_vel, vel)
            if len(acc) < 2:
                continue
            # step 3 -> jerk: difference of acceleration over time.
            t_acc = [t_vel[i] for i in e2]
            e3, jerk = _derivative_series(t_acc, acc)
            bad_local: list[int] = []
            for k, j in zip(e3, jerk, strict=True):
                if abs(j) > limit:
                    member_pos = e1[e2[k]]  # position in episode member list
                    global_idx = members[member_pos][0]
                    bad_local.append(global_idx)
                    excluded.setdefault(global_idx, []).append(
                        f"jerk {j:.1f} rad/s^3 exceeds ±{limit:g} "
                        f"(from {start_col})"
                    )
            checks.append({
                "name": f"robotics_jerk:{base}",
                "column": start_col,
                "status": "failed" if bad_local else "passed",
                "violations": len(bad_local),
                "indices": sorted(bad_local),
                "low": -limit, "high": limit,
                "detail": (
                    f"{len(bad_local)} sample(s): jerk derived from "
                    f"{start_col} exceeds ±{limit:g} rad/s^3."
                    if bad_local else
                    f"All jerk values derived from {start_col} within "
                    f"±{limit:g} rad/s^3."
                ),
            })
    flagged = sorted(excluded)
    statuses = {check.get("status") for check in checks}
    verdict = "failed" if "failed" in statuses else (
        "warning" if "warning" in statuses else "passed" if checks else "warning")
    return {"checks": checks, "excluded": excluded,
            "flagged_rows": flagged, "verdict": verdict}


# ---------------------------------------------------------------------------
# 4. units detection — degrees wearing a radians costume
# ---------------------------------------------------------------------------

def detect_units(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Suspect that joint position data is in DEGREES, not radians.

    Evidence: a position signal whose biggest absolute value is more
    than a full turn in radians makes no sense (> 2π ≈ 6.28), but in
    degrees anything up to 360 is normal. So: max|value| in (2π, 360]
    -> almost certainly degrees. Values beyond 360 are flagged as
    suspicious too (unwrapped degrees, or just broken).

    Returns {"verdict": "warning"|"passed",
             "likely_degree_signals": [...],
             "signals": {name: {"max_abs": ..., "likely_degrees": bool}},
             "checks": [...SimAPI-shaped warning checks...]}.
    """
    signals: dict[str, dict[str, Any]] = {}
    likely: list[str] = []
    suspicious: list[str] = []
    checks: list[dict[str, Any]] = []
    columns = sorted({
        str(col) for row in rows for col in row
        if str(col).startswith("joint") and str(col).endswith("_position")
    })
    for col in columns:
        values = [v for v in (_num(r.get(col)) for r in rows) if v is not None]
        if not values:
            continue
        max_abs = max(abs(v) for v in values)
        beyond = sum(1 for v in values if abs(v) > TWO_PI)
        is_degrees = max_abs > TWO_PI and max_abs <= 360.0 and beyond >= 1
        is_suspicious = max_abs > 360.0
        signals[col] = {"max_abs": max_abs, "likely_degrees": is_degrees,
                        "suspicious_range": is_suspicious,
                        "samples_beyond_2pi": beyond}
        if is_degrees:
            likely.append(col)
            checks.append({
                "name": f"units_likely_degrees:{col}", "column": col,
                "status": "warning", "violations": beyond,
                "detail": (
                    f"{col} reaches {max_abs:.1f} — impossible for radians "
                    f"(> 2π ≈ 6.28) but normal for degrees. This data looks "
                    f"like it was recorded in DEGREES while SimAPI limits "
                    f"assume radians. Convert with "
                    f"convert_degrees_to_radians() or declare units in "
                    f"your profile before trusting any verdict."
                ),
            })
        elif is_suspicious:
            suspicious.append(col)
            checks.append({
                "name": f"units_suspicious_range:{col}", "column": col,
                "status": "warning", "violations": beyond,
                "detail": (
                    f"{col} reaches {max_abs:.1f}, beyond 360. This could be "
                    "unwrapped degree data or corrupt values; confirm the "
                    "source units before trusting the result."
                ),
            })
    return {
        "verdict": "warning" if checks else "passed",
        "likely_degree_signals": likely,
        "suspicious_signals": suspicious,
        "signals": signals,
        "checks": checks,
        "detail": (
            f"{len(likely)} signal(s) look like degrees and "
            f"{len(suspicious)} have suspicious magnitudes."
            if checks else "No position signal looks like degrees or has a suspicious magnitude."
        ),
    }


def convert_degrees_to_radians(rows: list[dict[str, Any]],
                               signals: list[str] | None = None
                               ) -> list[dict[str, Any]]:
    """Return NEW rows with the named signals converted deg -> rad
    (× π/180). Original rows are never mutated. signals=None converts
    the signals detect_units() flags as likely degrees."""
    if signals is None:
        signals = detect_units(rows)["likely_degree_signals"]
    targets = set(signals)
    factor = math.pi / 180.0
    out: list[dict[str, Any]] = []
    for row in rows:
        new_row = dict(row)
        for col in targets:
            value = _num(new_row.get(col))
            if value is not None:
                new_row[col] = value * factor
        out.append(new_row)
    return out


# ---------------------------------------------------------------------------
# 5. dataset health score
# ---------------------------------------------------------------------------

def _band_for(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def dataset_health_score(episode_results: Any) -> dict[str, Any]:
    """One 0-100 health score for a dataset, from per-episode results.

    Input: either the dict returned by physical_ai.episode_quality()
    ({"episodes": [...], ...}) or a bare list of episode dicts with
    samples / verdict / training_ready / failure_labels / flagged_rows.

    The maths (kept simple on purpose, so it can be explained):
        score = 70% × (% of episodes that are training-ready)
              + 30% × (% of rows NOT flagged)
    Bands: A ≥ 90, B ≥ 75, C ≥ 60, D ≥ 40, F < 40.
    An empty dataset scores 0 / F — no data is not healthy data.
    """
    if isinstance(episode_results, dict):
        episodes = list(episode_results.get("episodes", []))
    else:
        episodes = list(episode_results or [])
    if not episodes:
        return {"score": 0, "band": "F", "letter_band": "F",
                "reasons": ["No episodes provided — nothing to score."],
                "top_reasons": ["No episodes provided — nothing to score."],
                "episodes": 0, "training_ready_episodes": 0,
                "total_rows": 0, "flagged_rows": 0}

    total_rows = 0
    flagged_rows = 0
    ready = 0
    label_counts: dict[str, int] = {}
    for episode in episodes:
        try:
            samples = int(episode.get("samples", 0))
        except (TypeError, ValueError, OverflowError):
            samples = 0
        total_rows += max(0, samples)

        raw_flagged = episode.get("flagged_rows", []) or []
        if isinstance(raw_flagged, (list, tuple, set)):
            flagged_rows += len({repr(index) for index in raw_flagged})

        labels = episode.get("failure_labels", []) or []
        if isinstance(labels, str):
            labels = [labels]
        for label in labels:
            label_counts[str(label)] = label_counts.get(str(label), 0) + 1

        episode_ready = episode.get("training_ready")
        if episode_ready is None:
            episode_ready = (
                episode.get("verdict") == "passed"
                and not raw_flagged
                and not labels
            )
        ready += int(bool(episode_ready))

    flagged_rows = min(flagged_rows, total_rows)
    episode_rate = ready / len(episodes)
    row_rate = 1.0 - flagged_rows / total_rows if total_rows else 0.0
    score = int(round(70 * episode_rate + 30 * row_rate))

    reasons: list[str] = []
    not_ready = len(episodes) - ready
    if not_ready:
        reasons.append(f"{not_ready} of {len(episodes)} episode(s) are "
                       f"not training-ready.")
    if flagged_rows and total_rows:
        reasons.append(f"{flagged_rows} of {total_rows} rows flagged "
                       f"({100.0 * flagged_rows / total_rows:.0f}%).")
    if not total_rows:
        reasons.append("No sample counts were provided — row health cannot be scored.")
    for label, count in sorted(label_counts.items(),
                               key=lambda kv: (-kv[1], kv[0]))[:3]:
        reasons.append(f"Most common failure: {label} "
                       f"(in {count} episode(s))." if count == max(label_counts.values())
                       else f"Failure label {label} in {count} episode(s).")
    if not reasons:
        reasons.append("All episodes training-ready, no rows flagged.")

    return {"score": score, "band": _band_for(score),
            "letter_band": _band_for(score),
            "reasons": reasons, "top_reasons": reasons,
            "episodes": len(episodes),
            "training_ready_episodes": ready,
            "total_rows": total_rows, "flagged_rows": flagged_rows}


# ---------------------------------------------------------------------------
# 6. failure clustering
# ---------------------------------------------------------------------------

_PLAIN_NAMES = {
    "teleport": "Impossible jump (teleport)",
    "robotics_derived_limit": "Impossible jump (teleport)",
    "limit_violation": "Value outside its allowed range",
    "robotics_limit": "Value outside its allowed range",
    "torque_saturation": "Motor pinned at its limit (saturation)",
    "frozen_sensor": "Sensor froze while the arm moved",
    "time_gap": "Hole in the timestamps",
    "robotics_sample_gaps": "Hole in the timestamps",
    "time_disorder": "Time went backwards or repeated",
    "robotics_time_order": "Time went backwards or repeated",
    "inconsistent_velocity": "Recorded speed disagrees with positions",
    "robotics_consistency": "Recorded value disagrees with the motion",
    "robotics_jerk": "Sudden jerk spike",
    "profile_guard": "No real robot profile was used",
}


def _plain_cluster_name(label: str, signal: str) -> str:
    for prefix, plain in _PLAIN_NAMES.items():
        if label == prefix or label.startswith(prefix):
            return f"{plain} — {signal}" if signal not in ("", "unknown") else plain
    pretty = label.replace("_", " ").replace(":", " on ")
    return f"{pretty} — {signal}" if signal not in ("", "unknown") else pretty


def cluster_failures(failures: list[dict[str, Any]]) -> dict[str, Any]:
    """Group failure dicts into a short, readable list of clusters.

    Accepts the shapes SimAPI already produces: check dicts
    ({"name": "robotics_limit:joint_1_torque", ...}), episode failure
    entries ({"label"/"failure_label": ..., "signal"/"column": ...}),
    optionally carrying row indices under flagged_rows / indices /
    row / rows.

    Groups by (label, signal). Returns clusters sorted by count
    (biggest problem first), each with a plain-English name and up to
    5 example row indices.
    """
    clusters: dict[tuple[str, str], dict[str, Any]] = {}
    total = 0
    for failure in failures or []:
        status = str(failure.get("status", "")).lower()
        if status and status not in {"failed", "warning"}:
            continue
        name = str(failure.get("name") or failure.get("label")
                   or failure.get("failure_label") or failure.get("check")
                   or "unknown")
        signal = str(failure.get("signal") or failure.get("column") or "")
        if not signal and ":" in name:
            signal = name.split(":", 1)[1]
        label = name.split(":", 1)[0] if ":" in name else name
        if not signal:
            signal = "unknown"
        candidates: list[Any] = []
        for field in ("flagged_rows", "indices", "rows"):
            value = failure.get(field)
            if isinstance(value, (list, tuple)):
                candidates.extend(value)
        if failure.get("row") is not None:
            candidates.append(failure.get("row"))
        row_indices = sorted({
            candidate for candidate in candidates
            if isinstance(candidate, int) and not isinstance(candidate, bool)
        })
        try:
            violations = int(failure.get("violations", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            violations = 0
        if status and violations <= 0 and not row_indices:
            # A warning without row indices (e.g. profile_guard) is still
            # a meaningful finding, while a passing/empty check was skipped.
            if status != "warning":
                continue
        occurrence_count = max(violations, len(row_indices), 1)
        total += occurrence_count
        key = (label, signal)
        cluster = clusters.setdefault(key, {
            "label": label, "check": name, "signal": signal, "count": 0,
            "example_rows": [], "example_row_indices": [],
            "name_plain": _plain_cluster_name(label, signal),
            "cluster_name": _plain_cluster_name(label, signal),
        })
        cluster["count"] += occurrence_count
        for cand in row_indices:
            if cand not in cluster["example_rows"]:
                if len(cluster["example_rows"]) < 5:
                    cluster["example_rows"].append(cand)
                    cluster["example_row_indices"].append(cand)
    ordered = sorted(clusters.values(),
                     key=lambda c: (-c["count"], c["label"], c["signal"]))
    return {
        "clusters": ordered,
        "total_failures": total,
        "verdict": "failed" if ordered else "passed",
        "detail": (
            f"{total} failure(s) grouped into {len(ordered)} cluster(s)."
            if ordered else "No failures to cluster."
        ),
    }


# ---------------------------------------------------------------------------
# 7. torque saturation trend
# ---------------------------------------------------------------------------

def torque_saturation_trend(rows: list[dict[str, Any]],
                            signal: str,
                            limit: Any) -> dict[str, Any]:
    """Is the motor spending MORE time near its limit late in the episode?

    Splits the episode's samples for `signal` into first half / second
    half. In each half, the "saturation fraction" is the share of
    samples within 5% of the limit (for a (min, max) limit, within 5%
    of the range of either end; for a single number, |value| ≥ 95% of
    it). Rising fraction = the motor is straining harder as the task
    goes on — an early warning of a dying motor, a too-heavy load, or
    a task the arm is barely strong enough for.

    Returns both halves' fractions, the change, and a plain trend word:
    "increasing" / "decreasing" / "flat" / "unknown" (too little data).
    """
    if isinstance(limit, (list, tuple)):
        if len(limit) != 2:
            raise ValueError("limit must be a finite positive value or [min, max] pair")
        low, high = _num(limit[0]), _num(limit[1])
        if low is None or high is None or low >= high:
            raise ValueError("limit range must contain finite bounds with min < max")
        limit_value: float | tuple[float, float] = (low, high)
    else:
        cap = _num(limit)
        if cap is None or cap == 0:
            raise ValueError("limit must be a finite non-zero value or [min, max] pair")
        limit_value = cap

    groups = _group_episodes(rows)
    if len(groups) > 1:
        episodes = []
        for episode_id, members in groups:
            result = torque_saturation_trend(
                [row for _, row in members], signal, limit_value
            )
            result["episode_id"] = episode_id
            episodes.append(result)
        return {
            "signal": signal,
            "samples": sum(episode["samples"] for episode in episodes),
            "trend": "unknown",
            "episodes": episodes,
            "detail": (
                "Rows contain multiple episodes; inspect the per-episode "
                "trends instead of combining them into one motor trend."
            ),
        }

    values = [v for v in (_num(r.get(signal)) for r in rows) if v is not None]

    def near_limit(v: float) -> bool:
        if isinstance(limit_value, tuple):
            lo, hi = limit_value
            width = hi - lo
            return v >= hi - 0.05 * width or v <= lo + 0.05 * width
        cap = abs(limit_value)
        return abs(v) >= 0.95 * cap

    if len(values) < 4:
        return {"signal": signal, "samples": len(values),
                "first_half_saturation": 0.0, "second_half_saturation": 0.0,
                "first_half_fraction": 0.0, "second_half_fraction": 0.0,
                "delta": 0.0, "trend": "unknown",
                "detail": "Too few samples to judge a trend (need ≥ 4)."}

    mid = len(values) // 2
    first, second = values[:mid], values[mid:]
    f1 = sum(1 for v in first if near_limit(v)) / len(first)
    f2 = sum(1 for v in second if near_limit(v)) / len(second)
    delta = f2 - f1
    trend = "increasing" if delta > 0.05 else (
        "decreasing" if delta < -0.05 else "flat")
    return {
        "signal": signal, "samples": len(values),
        "first_half_saturation": f1, "second_half_saturation": f2,
        "first_half_fraction": f1, "second_half_fraction": f2,
        "delta": delta, "trend": trend,
        "detail": (
            f"Samples within 5% of the limit: first half "
            f"{100 * f1:.0f}%, second half {100 * f2:.0f}% — "
            f"motor strain is {trend}."
        ),
    }
