"""Compare simulated and real robotics tables for distribution drift.

The module is deliberately independent of FastAPI and the validation engine.
Callers may pass validation reports produced by
``core.robotics_validation.check_robotics_limits``; only check names and
statuses are read here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

TIME_KEYS = ("time", "t", "timestamp", "simulation_time", "sim_time", "elapsed_time")
GROUP_KEYS = ("episode_id", "episode", "trajectory_id", "sequence_id")
_METADATA_KEYS = set(TIME_KEYS) | set(GROUP_KEYS) | {"frame_index", "step", "index"}


def _first_column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    by_normalized = {str(column).strip().lower().replace("-", "_").replace(" ", "_"): str(column)
                     for column in frame.columns}
    return next((by_normalized[name] for name in names if name in by_normalized), None)


def _numeric_signals(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    signals: dict[str, np.ndarray] = {}
    for column in frame.columns:
        name = str(column)
        normalized = name.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in _METADATA_KEYS:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        # Duplicate labels make frame[column] a DataFrame. Skip rather than
        # silently choose one of the user's signals.
        if isinstance(values, pd.DataFrame):
            continue
        array = values.to_numpy(dtype=float, na_value=np.nan)
        array = array[np.isfinite(array)]
        if array.size:
            signals[name] = array
    return signals


def _derived_joint_velocities(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    """Estimate interval-average velocity without crossing episode boundaries.

    Derived keys end in ``_velocity_fd`` so they remain distinct from any
    velocity sensor or controller values already present in the table.
    Rows are ordered by their time value within each episode before taking
    adjacent finite differences.
    """
    time_column = _first_column(frame, TIME_KEYS)
    if time_column is None:
        return {}
    group_column = _first_column(frame, GROUP_KEYS)
    time_values = pd.to_numeric(frame[time_column], errors="coerce")
    derived: dict[str, np.ndarray] = {}
    for position_column in frame.columns:
        name = str(position_column)
        normalized_name = name.strip().lower().replace("-", "_").replace(" ", "_")
        if not normalized_name.startswith("joint") or not normalized_name.endswith("_position"):
            continue
        positions = pd.to_numeric(frame[position_column], errors="coerce")
        if isinstance(positions, pd.DataFrame):
            continue
        work = pd.DataFrame({"time": time_values, "position": positions})
        if group_column is not None:
            work["group"] = frame[group_column].astype("string").fillna("(missing episode)")
            groups = work.groupby("group", sort=False, dropna=False)
        else:
            groups = [("Episode 1", work)]

        estimates: list[np.ndarray] = []
        for _, group in groups:
            ordered = group.sort_values("time", kind="stable")
            t = ordered["time"].to_numpy(dtype=float, na_value=np.nan)
            q = ordered["position"].to_numpy(dtype=float, na_value=np.nan)
            dt = np.diff(t)
            dq = np.diff(q)
            valid = np.isfinite(dt) & (dt > 0) & np.isfinite(dq)
            estimates.append(dq[valid] / dt[valid])
        if estimates:
            values = np.concatenate(estimates)
            values = values[np.isfinite(values)]
            if values.size:
                derived[name[:-len("position")] + "velocity_fd"] = values
    return derived


def _distribution(values: np.ndarray) -> dict[str, float]:
    array = values[np.isfinite(values)]
    p5, p95 = np.percentile(array, [5, 95])
    return {
        "min": float(np.min(array)),
        "max": float(np.max(array)),
        "mean": float(np.mean(array)),
        "std": float(np.std(array, ddof=0)),
        "p5": float(p5),
        "p95": float(p95),
    }


def _overlap(sim: dict[str, float], real: dict[str, float]) -> float:
    """Intersection length / union length of p5-p95 ranges."""
    left = max(sim["p5"], real["p5"])
    right = min(sim["p95"], real["p95"])
    intersection = max(0.0, right - left)
    union = max(sim["p95"], real["p95"]) - min(sim["p5"], real["p5"])
    if union == 0:
        return 1.0 if sim["p5"] == real["p5"] else 0.0
    return float(intersection / union)


def _checks(report: Mapping[str, Any] | None) -> dict[str, bool]:
    if not report:
        return {}
    raw_checks = report.get("checks")
    if not isinstance(raw_checks, list):
        raw_checks = report.get("robotics_checks")
    if not isinstance(raw_checks, list):
        return {}
    return {
        str(check["name"]): str(check.get("status", "")) == "passed"
        for check in raw_checks
        if isinstance(check, Mapping) and check.get("name") is not None
    }


def _validation_summary(
    frame: pd.DataFrame, report: Mapping[str, Any] | None
) -> dict[str, Any]:
    report = report or {}
    n_rows = len(frame)
    excluded = report.get("excluded")
    excluded_count = int(report.get("trials_excluded", 0) or 0)
    if excluded_count == 0 and isinstance(excluded, Mapping):
        excluded_count = len(excluded)
    elif excluded_count == 0 and isinstance(report.get("exclusions"), list):
        excluded_count = len(report["exclusions"])
    checks = _checks(report)
    checks_total = len(checks)
    checks_passed = sum(checks.values())
    status = report.get("status")
    if status is None:
        status = "failed" if any(not passed for passed in checks.values()) else "passed"
    return {
        "status": status,
        "training_ready": bool(report.get("training_ready", excluded_count == 0 and status == "passed")),
        "rows": n_rows,
        "excluded_count": excluded_count,
        "exclusion_rate": float(report.get("exclusion_rate", excluded_count / n_rows if n_rows else 0.0)),
        "checks_passed": int(checks_passed),
        "checks_total": checks_total,
    }


def compare_sim_real(
    sim_data: pd.DataFrame,
    real_data: pd.DataFrame,
    sim_validation: Mapping[str, Any] | None = None,
    real_validation: Mapping[str, Any] | None = None,
    *,
    drift_threshold: float = 0.5,
) -> dict[str, Any]:
    """Compare numeric signals and robotics check outcomes across two runs.

    ``sim_validation`` and ``real_validation`` are optional report mappings
    from the existing robotics validator. Pass those reports to populate the
    per-side validation summaries and the named check-pass comparison.
    """
    if not 0.0 <= drift_threshold <= 1.0:
        raise ValueError("drift_threshold must be between 0 and 1")

    sim_signals = _numeric_signals(sim_data)
    real_signals = _numeric_signals(real_data)
    sim_signals.update(_derived_joint_velocities(sim_data))
    real_signals.update(_derived_joint_velocities(real_data))

    sim_names, real_names = set(sim_signals), set(real_signals)
    common_names = sorted(sim_names & real_names)
    only_sim = sorted(sim_names - real_names)
    only_real = sorted(real_names - sim_names)
    signal_report: dict[str, dict[str, Any]] = {}
    any_drift = False
    for name in common_names:
        sim_stats = _distribution(sim_signals[name])
        real_stats = _distribution(real_signals[name])
        overlap = _overlap(sim_stats, real_stats)
        drift = overlap < drift_threshold
        any_drift = any_drift or drift
        signal_report[name] = {
            "sim": sim_stats,
            "real": real_stats,
            "overlap": overlap,
            "drift": drift,
        }

    sim_checks = _checks(sim_validation)
    real_checks = _checks(real_validation)
    all_check_names = sorted(set(sim_checks) | set(real_checks))
    check_pass_rates = {
        name: {"sim": sim_checks.get(name, False), "real": real_checks.get(name, False)}
        for name in all_check_names
    }
    check_mismatch = any(values["sim"] != values["real"] for values in check_pass_rates.values())

    return {
        "sim": _validation_summary(sim_data, sim_validation),
        "real": _validation_summary(real_data, real_validation),
        "signals": signal_report,
        "signals_only_in_sim": only_sim,
        "signals_only_in_real": only_real,
        "check_pass_rates": check_pass_rates,
        "verdict": "drift_detected" if any_drift or check_mismatch else "aligned",
    }
