"""Shared validation adapter for robot datasets loaded from external formats."""

from __future__ import annotations

from typing import Any

import pandas as pd

from core.robotics_engine import RoboticsValidationEngine


def validate_robotics_frame(
    data: pd.DataFrame,
    *,
    limits: dict[str, tuple[float, float]] | None = None,
    conditions: dict[str, float] | None = None,
    time_unit: str = "seconds",
) -> dict[str, Any]:
    """Run the same deterministic robotics engine used by the HTTP API."""
    frame = data.reset_index(drop=True)
    engine = RoboticsValidationEngine()
    report = engine.validate(
        frame,
        configured_limits=limits,
        source_rows=frame.to_dict(orient="records"),
        conditions=conditions,
    )
    excluded = {int(row): reasons for row, reasons in report["excluded"].items()}
    failures = sum(check.get("status") == "failed" for check in report["checks"])
    warnings = sum(check.get("status") == "warning" for check in report["checks"])
    unprofiled_warning = any(
        check.get("name") == "robotics_unprofiled_signal" and check.get("status") == "warning"
        for check in report["checks"]
    )
    status = "failed" if failures else "warning" if warnings or excluded else "passed"
    summary = dict(report["summary"])
    summary["time_unit"] = time_unit
    if time_unit != "seconds":
        summary.setdefault("assumptions", []).append(
            f"Time values use {time_unit}; velocity and acceleration are expressed per {time_unit}."
        )

    episodes = []
    episode_col = summary.get("episode_column")
    if episode_col and episode_col in frame.columns:
        for episode_id, episode_frame in frame.groupby(episode_col, sort=False, dropna=False):
            indices = set(int(index) for index in episode_frame.index)
            flagged = len(indices.intersection(excluded))
            episodes.append({
                "episode_id": str(episode_id),
                "rows": len(episode_frame),
                "excluded": flagged,
                "training_ready": flagged == 0 and not unprofiled_warning,
            })

    return {
        "status": status,
        "training_ready": not excluded and not failures and not warnings,
        "rows": len(data),
        "excluded_rows": len(excluded),
        "exclusions": excluded,
        "checks": report["checks"],
        "summary": summary,
        "episodes": episodes,
    }
