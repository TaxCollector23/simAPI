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


def test_unprofiled_torque_500_is_not_a_clean_pass():
    report = RoboticsValidationEngine().validate(pd.DataFrame([{"joint_1_torque": 500.0}]))

    torque = next(check for check in report["checks"] if check["name"] == "robotics_limit:joint_1_torque")
    assert torque["status"] == "failed"
    assert torque["low"] == -200.0
    assert torque["high"] == 200.0


def test_unprofiled_torque_50000_fails_with_limit_check():
    report = RoboticsValidationEngine().validate(pd.DataFrame([{"joint_1_torque": 50_000.0}]))

    torque = next(check for check in report["checks"] if check["name"] == "robotics_limit:joint_1_torque")
    assert torque["status"] == "failed"
    assert torque["violations"] == 1
    assert report["excluded"] == {0: ["joint_1_torque=50000 outside [-200, 200]"]}


def test_in_range_default_joint_signal_warns_and_is_named_in_summary():
    report = RoboticsValidationEngine().validate(pd.DataFrame([{"joint_1_torque": 25.0}]))

    warning = next(check for check in report["checks"] if check["name"] == "robotics_unprofiled_signal")
    assert warning == {
        "name": "robotics_unprofiled_signal",
        "status": "warning",
        "column": None,
        "violations": 0,
        "detail": (
            "Signals validated with screening defaults only — supply a profile "
            "(or import a URDF) for real limits: joint_1_torque"
        ),
    }
    assert report["summary"]["unprofiled_signals"] == ["joint_1_torque"]


def test_explicit_torque_limit_preserves_check_and_exclusion():
    report = RoboticsValidationEngine().validate(
        pd.DataFrame([{"joint_1_torque": 95.0}]),
        configured_limits={"joint_1_torque": (-70.0, 70.0)},
    )

    torque = next(check for check in report["checks"] if check["name"] == "robotics_limit:joint_1_torque")
    assert torque["status"] == "failed"
    assert torque["low"] == -70.0
    assert torque["high"] == 70.0
    assert report["excluded"] == {0: ["joint_1_torque=95 outside [-70, 70]"]}
    assert not any(check["name"] == "robotics_unprofiled_signal" for check in report["checks"])


def test_explicit_limits_covering_all_joint_signals_do_not_warn():
    report = RoboticsValidationEngine().validate(
        pd.DataFrame([{
            "joint_1_position": 0.25,
            "joint_1_velocity": 0.5,
            "joint_1_torque": 25.0,
        }]),
        configured_limits={
            "joint_1_position": (-1.0, 1.0),
            "joint_1_velocity": (-2.0, 2.0),
            "joint_1_torque": (-70.0, 70.0),
        },
    )

    assert not any(check["name"] == "robotics_unprofiled_signal" for check in report["checks"])
    assert "unprofiled_signals" not in report["summary"]


def test_api_caps_default_only_robotics_verdict_and_training_readiness(client):
    response = client.post("/v1/validate/physics-only", json={
        "data": [{"joint_1_torque": 25.0}],
        "simulation_type": "robotics",
    })

    assert response.status_code == 200
    body = response.json()
    warning = next(check for check in body["robotics_checks"] if check["name"] == "robotics_unprofiled_signal")
    assert warning["status"] == "warning"
    assert body["status"] == "warning"
    assert body["training_ready"] is False


def test_physics_validator_torque_screening_bound_is_tightened():
    from core.physics_validator import BOUNDS, PhysicsValidator, SimulationType

    assert BOUNDS[SimulationType.ROBOTICS]["joint_torque"] == (-200.0, 200.0)
    report = PhysicsValidator().validate(
        pd.DataFrame([{"joint_torque": 500.0}]), SimulationType.ROBOTICS, {}, auto_profile=False
    )
    check = next(check for check in report.issues if check.name == "bounds_joint_torque")
    assert check.status.value == "failed"


def test_external_validation_adapter_marks_episodes_not_ready_for_unprofiled_warning():
    from integrations.robotics_validation import validate_robotics_frame

    report = validate_robotics_frame(pd.DataFrame([
        {"episode_id": "pick", "time": 0.0, "joint_1_torque": 10.0},
        {"episode_id": "place", "time": 0.0, "joint_1_torque": 12.0},
    ]))

    assert report["status"] == "warning"
    assert report["training_ready"] is False
    assert all(episode["excluded"] == 0 for episode in report["episodes"])
    assert all(episode["training_ready"] is False for episode in report["episodes"])


def test_external_validation_adapter_keeps_other_warnings_out_of_episode_readiness():
    from integrations.robotics_validation import validate_robotics_frame

    report = validate_robotics_frame(pd.DataFrame([
        {"episode_id": "state_only", "temperature": 25.0},
    ]))

    assert any(check["status"] == "warning" for check in report["checks"])
    assert not any(check["name"] == "robotics_unprofiled_signal" for check in report["checks"])
    assert report["episodes"][0]["training_ready"] is True
