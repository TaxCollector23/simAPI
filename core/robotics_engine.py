"""Composable validation engine for robot trajectory records.

The engine owns orchestration and report assembly. Individual check suites own
one family of rules, so dynamics, contact, and sensor checks can be added
without growing a single robotics validation function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import pandas as pd

from core.robotics_evidence import build_evidence
from core.robotics_trajectory import analyze_trajectories, normalize

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
        summary: dict[str, Any] = {
            "engine_version": None,
            "episodes": [],
            "time_column": None,
            "episode_column": None,
            "assumptions": [],
        }
        for suite in self.suites:
            result = suite.run(context)
            checks.extend(result.checks)
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

        evidence = build_evidence(rows, checks, limits, options, summary)
        return {"checks": checks, "excluded": excluded, "summary": summary, "evidence": evidence}
