"""Composable validation engine for robot trajectory records.

The engine owns orchestration and report assembly. Individual check suites own
one family of rules, so dynamics, contact, and sensor checks can be added
without growing a single robotics validation function.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol

import pandas as pd

from core.kinematics import URDFGeometry, forward_kinematics, joint_signal_name, parse_urdf_geometry
from core.robotics_evidence import build_evidence
from core.robotics_trajectory import GROUP_KEYS, TIME_KEYS, analyze_trajectories, normalize, number

# Tight screening bounds only; these are still not robot limits. Robot-specific
# values should come from the model or controller and replace these per signal.
DEFAULT_ROBOTICS_LIMITS: dict[str, tuple[float, float]] = {
    "joint_torque": (-200.0, 200.0),
    "joint_velocity": (-10.0, 10.0),
    "joint_acceleration": (-50.0, 50.0),
    "joint_position": (-4 * 3.141592653589793, 4 * 3.141592653589793),
    "end_effector_force": (-1_000.0, 1_000.0),
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

_JOINT_SIGNAL_SUFFIXES = ("_position", "_velocity", "_acceleration", "_torque")


@dataclass(frozen=True)
class RoboticsValidationContext:
    """Shared run inputs with canonicalized configured and resolved limits."""

    data: pd.DataFrame
    source_rows: list[dict[str, Any]]
    limits: dict[str, tuple[float, float]]
    configured_limits: dict[str, tuple[float, float]]
    conditions: dict[str, float]


@dataclass
class RoboticsSuiteResult:
    """Findings returned by one independently implemented check family."""

    checks: list[dict[str, Any]] = field(default_factory=list)
    excluded: dict[int, list[str]] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)


class RoboticsCheckSuite(Protocol):
    """Extension point for a robotics validation family."""

    name: str

    def run(self, context: RoboticsValidationContext) -> RoboticsSuiteResult:
        """Evaluate this suite against one run."""


class SignalLimitsSuite:
    """Apply configured and broad plausibility bounds to scalar signals."""

    name = "signal_limits"

    def run(self, context: RoboticsValidationContext) -> RoboticsSuiteResult:
        columns = {normalize(str(column)): column for column in context.data.columns}
        checks: list[dict[str, Any]] = []
        excluded: dict[int, list[str]] = {}

        for canonical, (low, high) in context.limits.items():
            source_column = columns.get(canonical)
            if source_column is None:
                if canonical in context.configured_limits:
                    checks.append(
                        {
                            "name": f"robotics_limit:{canonical}",
                            "column": canonical,
                            "status": "failed",
                            "low": low,
                            "high": high,
                            "violations": 0,
                            "detail": f"Configured limit was not evaluated because column '{canonical}' is missing.",
                        }
                    )
                    for row in context.data.index:
                        excluded.setdefault(int(row), []).append(
                            f"configured signal '{canonical}' is missing"
                        )
                continue

            values = pd.to_numeric(context.data[source_column], errors="coerce")
            outside = (
                values.isna() | values.isin([float("inf"), float("-inf")]) | (values < low) | (values > high)
            )
            bad_rows = [int(index) for index in context.data.index[outside]]
            status = "failed" if bad_rows else "passed"
            detail = (
                f"{len(bad_rows)} sample(s) missing, non-finite, or outside [{low:g}, {high:g}]"
                if bad_rows
                else f"All samples within [{low:g}, {high:g}]"
            )
            checks.append(
                {
                    "name": f"robotics_limit:{canonical}",
                    "column": str(source_column),
                    "status": status,
                    "low": low,
                    "high": high,
                    "violations": len(bad_rows),
                    "detail": detail,
                }
            )
            for row in bad_rows:
                value = float(values.loc[row])
                excluded.setdefault(row, []).append(f"{source_column}={value:g} outside [{low:g}, {high:g}]")

        return RoboticsSuiteResult(checks=checks, excluded=excluded)


class TrajectorySuite:
    """Check temporal order, sampling gaps, and finite-difference motion."""

    name = "trajectory"

    def run(self, context: RoboticsValidationContext) -> RoboticsSuiteResult:
        result = analyze_trajectories(context.source_rows, context.configured_limits, context.conditions)
        return RoboticsSuiteResult(
            checks=result["checks"],
            excluded=result["excluded"],
            summary=result["summary"],
        )


class KinematicsSuite:
    """Compare reported end-effector positions with a parsed URDF FK chain."""

    name = "kinematics"
    _END_EFFECTOR_COLUMNS = (
        ("end_effector_x", "end_effector_y", "end_effector_z"),
        ("end_effector_position_x", "end_effector_position_y", "end_effector_position_z"),
    )

    def __init__(
        self,
        urdf_geometry: URDFGeometry | str,
        joint_signal_map: dict[str, str] | None = None,
        tolerance_m: float = 0.01,
        max_evaluations: int = 10_000,
    ) -> None:
        if isinstance(urdf_geometry, str):
            urdf_geometry = parse_urdf_geometry(urdf_geometry)
        if not isinstance(urdf_geometry, URDFGeometry):
            raise TypeError("urdf_geometry must be URDFGeometry or URDF XML text")
        if not math.isfinite(tolerance_m) or tolerance_m < 0:
            raise ValueError("tolerance_m must be finite and non-negative")
        if isinstance(max_evaluations, bool) or not isinstance(max_evaluations, int) or max_evaluations < 1:
            raise ValueError("max_evaluations must be a positive integer")
        self.urdf_geometry = urdf_geometry
        self.joint_signal_map = {
            str(joint): normalize(str(signal)) for joint, signal in (joint_signal_map or {}).items()
        }
        self.tolerance_m = float(tolerance_m)
        self.max_evaluations = max_evaluations

    def run(self, context: RoboticsValidationContext) -> RoboticsSuiteResult:
        columns = {normalize(str(column)) for column in context.data.columns}
        rows = [{normalize(str(key)): value for key, value in row.items()} for row in context.source_rows]
        if len(rows) > self.max_evaluations:
            raise ValueError(
                f"URDF FK evaluation is limited to {self.max_evaluations} sample(s); received {len(rows)}."
            )
        endpoint_columns = next(
            (signals for signals in self._END_EFFECTOR_COLUMNS if set(signals).issubset(columns)),
            None,
        )
        joint_signals = {
            joint.name: self.joint_signal_map.get(joint.name, normalize(joint_signal_name(joint.name)))
            for joint in self.urdf_geometry.active_joints
        }
        required_signals = set(joint_signals.values())
        time_key = next((key for key in TIME_KEYS if key in columns), None)
        group_key = next((key for key in GROUP_KEYS if key in columns), None)
        checks: list[dict[str, Any]] = []
        excluded: dict[int, list[str]] = {}
        evidence: list[dict[str, Any]] = []
        failed_indices: list[int] = []
        skipped_reasons: dict[int, str] = {}
        evaluated = 0

        if endpoint_columns is None:
            skipped_reasons = {
                index: "URDF FK could not run because reported end-effector x, y, and z signals are missing."
                for index in range(len(rows))
            }
        elif not required_signals.issubset(columns):
            missing_signals = sorted(required_signals.difference(columns))
            reason = (
                "URDF FK could not run because joint position signals are missing: "
                + ", ".join(missing_signals)
                + "."
            )
            skipped_reasons = {index: reason for index in range(len(rows))}

        for index, row in enumerate(rows) if endpoint_columns is not None and required_signals.issubset(columns) else ():
            joint_values: dict[str, float] = {}
            missing = False
            for _joint_name, signal in joint_signals.items():
                value = number(row.get(signal))
                if value is None:
                    missing = True
                    break
                joint_values[signal] = value
            reported_values = [number(row.get(signal)) for signal in endpoint_columns]
            if missing:
                skipped_reasons[index] = "URDF FK could not run because a joint position is missing or non-finite."
                continue
            if any(value is None for value in reported_values):
                skipped_reasons[index] = "URDF FK could not run because reported end-effector x, y, or z is missing or non-finite."
                continue
            computed = forward_kinematics(self.urdf_geometry, joint_values, joint_signals)
            reported = tuple(float(value) for value in reported_values if value is not None)
            distance = math.dist(computed, reported)
            evaluated += 1
            if distance <= self.tolerance_m:
                continue
            failed_indices.append(index)
            detail = (
                f"Reported end-effector position differs from URDF forward kinematics by "
                f"{distance:.6g} m, above the {self.tolerance_m:.6g} m tolerance."
            )
            excluded[index] = [detail]
            normalized_row = rows[index]
            episode_id = str(normalized_row.get(group_key, "(missing episode)")) if group_key else "Episode 1"
            time_value = number(normalized_row.get(time_key)) if time_key else None
            evidence.append({
                "check": "robotics_kinematics:end_effector_position",
                "status": "failed",
                "signal": "end_effector_position",
                "episode_id": episode_id,
                "sample_index": index,
                "time": time_value,
                "observed": distance,
                "expected": [0.0, self.tolerance_m],
                "detail": detail,
                "computed_position": {axis: value for axis, value in zip(("x", "y", "z"), computed, strict=True)},
                "reported_position": {axis: value for axis, value in zip(("x", "y", "z"), reported, strict=True)},
                "distance_m": distance,
            })

        for index, reason in skipped_reasons.items():
            excluded[index] = [reason]
        summary = {
            "kinematics": {
                "evaluated_rows": evaluated,
                "skipped_rows": len(skipped_reasons),
                "total_rows": len(rows),
                "coverage": evaluated / len(rows) if rows else 0.0,
                "tolerance_m": self.tolerance_m,
            }
        }
        if skipped_reasons:
            checks.append({
                "name": "robotics_kinematics:coverage",
                "column": "end_effector_position",
                "status": "warning",
                "indices": sorted(skipped_reasons),
                "violations": len(skipped_reasons),
                "detail": (
                    f"URDF FK evaluated {evaluated} of {len(rows)} sample(s); "
                    f"{len(skipped_reasons)} sample(s) could not be evaluated."
                ),
            })
        if not evaluated:
            return RoboticsSuiteResult(checks=checks, excluded=excluded, summary=summary)
        count_failed = len(failed_indices)
        status = "failed" if count_failed else "passed"
        detail = (
            f"{count_failed} sample(s) exceed the {self.tolerance_m:g} m end-effector position tolerance."
            if count_failed
            else f"All {evaluated} evaluated sample(s) are within the {self.tolerance_m:g} m end-effector position tolerance."
        )
        checks.append({
            "name": "robotics_kinematics:end_effector_position",
            "column": "end_effector_position",
            "status": status,
            "low": 0.0,
            "high": self.tolerance_m,
            "indices": failed_indices,
            "violations": count_failed,
            "detail": detail,
        })
        return RoboticsSuiteResult(checks=checks, excluded=excluded, summary=summary, evidence=evidence)


class RoboticsValidationEngine:
    """Run an ordered collection of checks and assemble a stable report.

    The default suite list contains scalar-limit and trajectory checks. A
    caller can supply an ordered replacement list or append custom suites to
    the default list. Suite order is observable in the returned check list.
    """

    def __init__(self, suites: list[RoboticsCheckSuite] | None = None) -> None:
        self.suites: list[RoboticsCheckSuite] = (
            list(suites) if suites is not None else [SignalLimitsSuite(), TrajectorySuite()]
        )

    def validate(
        self,
        data: pd.DataFrame,
        configured_limits: dict[str, tuple[float, float]] | None = None,
        source_rows: list[dict[str, Any]] | None = None,
        conditions: dict[str, float] | None = None,
        additional_suites: list[RoboticsCheckSuite] | None = None,
    ) -> dict[str, Any]:
        configured = {
            normalize(str(signal)): (float(bounds[0]), float(bounds[1]))
            for signal, bounds in (configured_limits or {}).items()
        }
        limits = dict(DEFAULT_ROBOTICS_LIMITS)
        for column in data.columns:
            canonical = normalize(str(column))
            if canonical.startswith("joint"):
                for quantity in ("position", "velocity", "acceleration", "torque"):
                    if canonical.endswith("_" + quantity):
                        limits[canonical] = DEFAULT_ROBOTICS_LIMITS["joint_" + quantity]
        limits.update(configured)

        # These defaults screen for implausible values but cannot represent a
        # particular robot. Track only present joint signals for which the
        # resolved bound came from the screening defaults, without changing
        # the existing effort/torque naming behavior.
        unprofiled_signals = sorted(
            {
                normalize(str(column))
                for column in data.columns
                if normalize(str(column)).startswith("joint_")
                and normalize(str(column)) in limits
                and normalize(str(column)) not in configured
            }
        )
        joint_signals = sorted(
            {
                normalize(str(column))
                for column in data.columns
                if normalize(str(column)).startswith("joint")
                and normalize(str(column)).endswith(_JOINT_SIGNAL_SUFFIXES)
            }
        )
        configured_joint_signals = set(joint_signals).intersection(configured)
        fallback_signals = sorted(set(joint_signals).difference(configured_joint_signals))
        if joint_signals and len(configured_joint_signals) == len(joint_signals):
            limits_source = "profile"
        elif configured_joint_signals:
            limits_source = "mixed"
        else:
            limits_source = "defaults"
        screening_warnings = (
            [
                "screening defaults used for "
                + ", ".join(fallback_signals)
                + " — supply a profile (or import a URDF) for real limits"
            ]
            if fallback_signals
            else []
        )

        rows = source_rows if source_rows is not None else data.to_dict("records")
        options = dict(conditions or {})
        context = RoboticsValidationContext(
            data=data,
            source_rows=rows,
            limits=limits,
            configured_limits=configured,
            conditions=options,
        )
        checks: list[dict[str, Any]] = []
        excluded: dict[int, list[str]] = {}
        extra_evidence: list[dict[str, Any]] = []
        summary: dict[str, Any] = {
            "engine_version": None,
            "episodes": [],
            "time_column": None,
            "episode_column": None,
            "assumptions": [],
            "limits_source": limits_source,
            "limit_fallback_signals": fallback_signals,
        }
        suites = [*self.suites, *(additional_suites or [])]
        for suite in suites:
            result = suite.run(context)
            checks.extend(result.checks)
            extra_evidence.extend(result.evidence)
            for row, reasons in result.excluded.items():
                excluded.setdefault(row, []).extend(reasons)
            summary.update(result.summary)

        if unprofiled_signals:
            checks.append(
                {
                    "name": "robotics_unprofiled_signal",
                    "status": "warning",
                    "column": None,
                    "violations": 0,
                    "detail": (
                        "Signals validated with screening defaults only — supply a profile "
                        "(or import a URDF) for real limits: "
                        + ", ".join(unprofiled_signals)
                    ),
                }
            )
            summary["unprofiled_signals"] = unprofiled_signals

        episode_key = summary.get("episode_column")
        episode_counts: dict[str, int] = {}
        for row in excluded:
            record = {normalize(str(key)): value for key, value in rows[row].items()}
            episode = str(record.get(episode_key, "(missing episode)")) if episode_key else "Episode 1"
            episode_counts[episode] = episode_counts.get(episode, 0) + 1
        for episode in summary.get("episodes", []):
            episode["flagged_samples"] = episode_counts.get(episode["episode_id"], 0)

        # KinematicsSuite supplies richer computed-vs-reported sample evidence.
        # The generic builder cannot reconstruct those values from a scalar
        # column, so skip only that check there and append its suite evidence.
        ordinary_checks = [
            check for check in checks
            if check.get("name") != "robotics_kinematics:end_effector_position"
        ]
        evidence = build_evidence(rows, ordinary_checks, limits, options, summary)
        if extra_evidence:
            total = evidence["total"] + len(extra_evidence)
            entries = (evidence["entries"] + extra_evidence)[:1000]
            evidence = {"entries": entries, "total": total, "truncated": total > len(entries)}
        return {
            "checks": checks,
            "excluded": excluded,
            "summary": summary,
            "evidence": evidence,
            "screening_warnings": screening_warnings,
        }
