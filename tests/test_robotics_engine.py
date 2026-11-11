"""Composable suites share the standard robotics report and evidence path."""

import pandas as pd

from core.robotics_engine import (
    RoboticsSuiteResult,
    RoboticsValidationEngine,
)
from core.robotics_validation import check_robotics_limits


class WorkspaceMarginSuite:
    name = "workspace_margin"

    def run(self, context):
        assert context.conditions["workspace_margin_min"] == 0.0
        assert context.conditions["workspace_margin_max"] == 1.0
        check = {
            "name": "robotics_workspace_margin",
            "column": "workspace_margin",
            "status": "failed",
            "low": 0.0,
            "high": 1.0,
            "indices": [1],
            "violations": 1,
            "detail": "Tool pose leaves the allowed workspace margin.",
        }
        return RoboticsSuiteResult(
            checks=[check],
            excluded={1: [check["detail"]]},
        )


def test_custom_suite_uses_context_and_shared_report_assembly():
    rows = [
        {"episode_id": "pick", "time": 0.0, "workspace_margin": 0.25},
        {"episode_id": "pick", "time": 0.1, "workspace_margin": -0.05},
    ]
    engine = RoboticsValidationEngine()
    engine.suites.append(WorkspaceMarginSuite())

    report = check_robotics_limits(
        pd.DataFrame(rows),
        conditions={"workspace_margin_min": 0.0, "workspace_margin_max": 1.0},
        source_rows=rows,
        engine=engine,
    )

    check = next(c for c in report["checks"] if c["name"] == "robotics_workspace_margin")
    evidence = next(e for e in report["evidence"]["entries"] if e["check"] == check["name"])
    assert report["excluded"] == {1: ["Tool pose leaves the allowed workspace margin."]}
    assert report["summary"]["episodes"][0]["flagged_samples"] == 1
    assert evidence["sample_index"] == 1
    assert evidence["signal"] == "workspace_margin"
    assert evidence["observed"] == -0.05
    assert evidence["expected"] == [0.0, 1.0]


def test_engine_can_run_replacement_suite_list_without_trajectory_suite():
    class EmptySuite:
        name = "empty"

        def run(self, context):
            assert context.source_rows == [{"temperature": 23.0}]
            return RoboticsSuiteResult()

    report = RoboticsValidationEngine([EmptySuite()]).validate(pd.DataFrame([{"temperature": 23.0}]))

    assert report["checks"] == []
    assert report["summary"] == {
        "engine_version": None,
        "episodes": [],
        "time_column": None,
        "episode_column": None,
        "assumptions": [],
    }
    assert report["evidence"] == {"entries": [], "total": 0, "truncated": False}
