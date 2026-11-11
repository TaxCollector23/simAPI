"""Backward-compatible entry point for manipulation validation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.robotics_engine import DEFAULT_ROBOTICS_LIMITS, RoboticsValidationEngine

__all__ = ["DEFAULT_ROBOTICS_LIMITS", "check_robotics_limits"]


def check_robotics_limits(
    data: pd.DataFrame,
    configured_limits: dict[str, tuple[float, float]] | None = None,
    source_rows: list[dict[str, Any]] | None = None,
    conditions: dict[str, float] | None = None,
    *,
    engine: RoboticsValidationEngine | None = None,
) -> dict[str, Any]:
    """Validate one run through the composable robotics engine.

    The established function signature and report shape remain available to
    existing API callers. New integrations can inject an engine with additional
    check suites.
    """
    runner = engine or RoboticsValidationEngine()
    return runner.validate(data, configured_limits, source_rows, conditions)
