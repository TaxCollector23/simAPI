"""Actuator chatter (spectral) and energy conservation check suites."""

import numpy as np
import pandas as pd

from core.physical_ai import episode_quality, export_clean_dataset
from core.robotics_validation import check_robotics_limits

DT = 0.01


def _chirp_free_rows(n=128, chatter=False):
    """Smooth 1 Hz joint motion; optionally with 30 Hz chatter in the second half."""
    times = np.arange(n) * DT
    velocity = np.sin(2.0 * np.pi * 1.0 * times)
    if chatter:
        gate = (np.arange(n) >= n // 2).astype(float)
        velocity = velocity + 1.5 * gate * np.sin(2.0 * np.pi * 30.0 * times)
    return [
        {"episode_id": "run", "time": float(t), "joint_1_position": float(v) * DT, "joint_1_velocity": float(v)}
        for t, v in zip(times, velocity, strict=True)
    ]


def _physics_rows(n=200, explosion_at=None, effort_column="joint_1_torque", gravity_torque=0.2):
    """Self-consistent inertia physics: effort = I*acceleration + constant gravity torque."""
    inertia = 0.5
    times = np.arange(n) * DT
    velocity = 0.5 * np.sin(2.0 * np.pi * 0.5 * times)
    acceleration = np.gradient(velocity, DT)
    effort = inertia * acceleration + gravity_torque
    if explosion_at is not None:
        velocity[explosion_at] += 6.0  # energy injected by nothing: contact-solver explosion
    return [
        {
            "episode_id": "run",
            "time": float(t),
            "joint_1_position": 0.0,
            "joint_1_velocity": float(v),
            effort_column: float(e),
        }
        for t, v, e in zip(times, velocity, effort, strict=True)
    ]


def _report(rows, conditions):
    return check_robotics_limits(pd.DataFrame(rows), conditions=conditions, source_rows=rows)


def _check(report, name):
    return next(c for c in report["checks"] if c["name"] == name)


# ── Actuator chatter ────────────────────────────────────────────────────────────

def test_smooth_motion_passes_chatter_check():
    report = _report(_chirp_free_rows(), {"chatter_min_frequency_hz": 10.0, "max_chatter_power_ratio": 0.25})
    check = _check(report, "robotics_chatter:joint_1_velocity")
    assert check["status"] == "passed"
    assert check["indices"] == []


def test_high_frequency_oscillation_is_flagged():
    report = _report(_chirp_free_rows(chatter=True), {"chatter_min_frequency_hz": 10.0, "max_chatter_power_ratio": 0.25})
    check = _check(report, "robotics_chatter:joint_1_velocity")
    assert check["status"] == "failed"
    assert check["indices"], "chattering windows must flag their samples"
    # Only the second half carries the 30 Hz component; early samples stay clean.
    assert min(check["indices"]) >= 32
    # Flagged rows are excluded with a reason.
    assert any("chatter" in reason for reasons in report["excluded"].values() for reason in reasons)


def test_chatter_evidence_points_to_the_flagged_interval_and_threshold():
    report = _report(
        _chirp_free_rows(chatter=True),
        {"chatter_min_frequency_hz": 10.0, "max_chatter_power_ratio": 0.25},
    )

    evidence = next(
        item for item in report["evidence"]["entries"]
        if item["check"] == "robotics_chatter:joint_1_velocity"
    )
    assert evidence["signal"] == "joint_1_velocity"
    assert evidence["episode_id"] == "run"
    assert evidence["interval_start"] < evidence["time"]
    assert evidence["expected"] == [0.0, 0.25]
    assert evidence["unit"] == "ratio"
    assert evidence["measurement"] == "High-frequency power ratio"


def test_chatter_is_opt_in_and_absent_by_default():
    report = _report(_chirp_free_rows(chatter=True), {})
    assert not any(c["name"].startswith("robotics_chatter") for c in report["checks"])


def test_chatter_without_time_column_is_not_evaluated():
    rows = [{"episode_id": "run", "joint_1_velocity": v} for v in np.sin(np.arange(128) * 0.3)]
    report = _report(rows, {"chatter_min_frequency_hz": 10.0})
    check = _check(report, "robotics_chatter:joint_1_velocity")
    assert check["status"] == "warning"
    assert "not evaluated" in check["detail"].lower()


def test_chatter_with_non_uniform_sampling_is_not_evaluated():
    rows = _chirp_free_rows(chatter=True)
    # Alternate 5 ms / 15 ms intervals: 50% deviation from the median step.
    times = [0.0]
    for index in range(1, len(rows)):
        times.append(times[-1] + (0.005 if index % 2 else 0.015))
    for row, t in zip(rows, times, strict=True):
        row["time"] = t
    report = _report(rows, {"chatter_min_frequency_hz": 10.0})
    check = _check(report, "robotics_chatter:joint_1_velocity")
    assert check["status"] == "warning"
    assert "non_uniform_sampling" in check["detail"]


def test_humanoid_foot_slip_requires_and_checks_velocity_signals():
    rows = [{
        "left_foot_contact_force_z": 5.0,
        "left_foot_linear_velocity_x": 0.3,
        "left_foot_linear_velocity_y": 0.0,
    }]
    report = _report(rows, {"max_foot_slip_mps": 0.1})
    assert _check(report, "robotics_foot_slip:left_foot")["status"] == "failed"

    report = _report([{"left_foot_contact_force_z": 5.0}], {"max_foot_slip_mps": 0.1})
    check = _check(report, "robotics_foot_slip:not_evaluated:left_foot")
    assert check["status"] == "warning"
    assert "linear_velocity_x" in check["detail"]


def test_humanoid_foot_slip_evidence_preserves_original_row_without_valid_time():
    rows = [{
        "episode_id": "walk",
        "time": "invalid",
        "left_foot_contact_force_z": 5.0,
        "left_foot_linear_velocity_x": 0.3,
        "left_foot_linear_velocity_y": 0.0,
    }]

    report = _report(rows, {"max_foot_slip_mps": 0.1})
    evidence = next(
        item for item in report["evidence"]["entries"]
        if item["check"] == "robotics_foot_slip:left_foot"
    )
    assert evidence["sample_index"] == 0
    assert evidence["episode_id"] == "walk"
    assert evidence["time"] is None
    assert evidence["signal"] == "left_foot_linear_velocity_x"
    assert evidence["observed"] == 0.3
    assert evidence["expected"] == [0.0, 0.1]
    assert evidence["unit"] == "m/s"


def test_stream_skew_evidence_reports_computed_value_and_configured_limit():
    rows = [
        {"episode_id": "walk", "time": 0.0, "t_cam": 0.0, "t_joint": 0.0},
        {"episode_id": "walk", "time": 0.01, "t_cam": 0.03, "t_joint": 0.01},
    ]

    report = _report(rows, {"max_sync_skew_ms": 10.0})
    evidence = next(
        item for item in report["evidence"]["entries"]
        if item["check"] == "robotics_stream_skew:camera_joint"
    )
    assert evidence["sample_index"] == 1
    assert evidence["time"] == 0.01
    assert evidence["signal"] == "t_cam"
    assert np.isclose(evidence["observed"], 20.0)
    assert evidence["expected"] == [0.0, 10.0]
    assert evidence["unit"] == "ms"
    assert evidence["measurement"] == "Camera / joint timestamp skew"


def test_chatter_with_too_few_samples_is_not_evaluated():
    rows = _chirp_free_rows(n=10, chatter=True)
    report = _report(rows, {"chatter_min_frequency_hz": 10.0})
    check = _check(report, "robotics_chatter:joint_1_velocity")
    assert check["status"] == "warning"
    assert "too_few_samples" in check["detail"]


def test_chatter_without_joint_velocity_signals_warns():
    rows = [{"episode_id": "run", "time": i * DT, "joint_1_position": 0.1} for i in range(64)]
    report = _report(rows, {"chatter_min_frequency_hz": 10.0})
    check = _check(report, "robotics_chatter:not_evaluated")
    assert check["status"] == "warning"


def test_chatter_reports_summary():
    report = _report(_chirp_free_rows(chatter=True), {"chatter_min_frequency_hz": 10.0, "max_chatter_power_ratio": 0.25})
    summary = report["summary"]["actuator_chatter"]
    assert summary["enabled"] is True
    assert summary["evaluated_signals"] == 1
    assert summary["max_power_ratio"] == 0.25


# ── Energy conservation ─────────────────────────────────────────────────────────

def test_consistent_physics_with_gravity_passes_energy_check():
    report = _report(_physics_rows(), {"energy_anomaly_factor": 100.0})
    check = _check(report, "robotics_energy:joint_1")
    assert check["status"] == "passed"
    assert check["indices"] == []


def test_unexplained_energy_spike_is_flagged():
    report = _report(_physics_rows(explosion_at=100), {"energy_anomaly_factor": 100.0})
    check = _check(report, "robotics_energy:joint_1")
    assert check["status"] == "failed"
    # The interval ending at the teleported sample is the violation.
    assert 100 in check["indices"]
    assert any("energy" in reason or "kinetic" in reason
               for reason in report["excluded"].get(100, []))


def test_energy_evidence_reports_residual_at_the_flagged_interval():
    report = _report(_physics_rows(explosion_at=100), {"energy_anomaly_factor": 100.0})

    evidence = next(
        item for item in report["evidence"]["entries"]
        if item["check"] == "robotics_energy:joint_1"
    )
    assert evidence["sample_index"] == 100
    assert evidence["signal"] == "joint_1_velocity"
    assert evidence["interval_start"] < evidence["time"]
    assert abs(evidence["observed"]) > 100.0
    assert evidence["expected"] == [-100.0, 100.0]
    assert evidence["unit"] == "×"
    assert evidence["measurement"] == "Normalized energy residual"


def test_energy_check_is_opt_in_and_absent_by_default():
    report = _report(_physics_rows(explosion_at=100), {})
    assert not any(c["name"].startswith("robotics_energy") for c in report["checks"])


def test_energy_check_accepts_effort_alias():
    rows = _physics_rows(effort_column="joint_1_effort")
    report = _report(rows, {"energy_anomaly_factor": 100.0})
    check = _check(report, "robotics_energy:joint_1")
    assert check["status"] == "passed"


def test_energy_check_warns_when_effort_signal_missing():
    rows = _physics_rows()
    for row in rows:
        del row["joint_1_torque"]
    report = _report(rows, {"energy_anomaly_factor": 100.0})
    check = _check(report, "robotics_energy:joint_1")
    assert check["status"] == "warning"
    assert "not evaluated" in check["detail"].lower()


def test_energy_check_rejects_invalid_factor():
    report = _report(_physics_rows(), {"energy_anomaly_factor": 0.5})
    check = _check(report, "robotics_energy:not_evaluated")
    assert check["status"] == "warning"
    assert "greater than 1" in check["detail"]


def test_energy_reports_summary():
    report = _report(_physics_rows(), {"energy_anomaly_factor": 100.0})
    summary = report["summary"]["energy_conservation"]
    assert summary["enabled"] is True
    assert summary["evaluated_signals"] == 1
    assert summary["anomaly_factor"] == 100.0


# ── Physical AI integration (labels + clean export) ────────────────────────────

def test_episode_quality_labels_chatter_episode():
    rows = _chirp_free_rows(chatter=True) + _chirp_free_rows()
    for row in rows[:128]:
        row["episode_id"] = "chattery"
    for row in rows[128:]:
        row["episode_id"] = "clean"
    quality = episode_quality(rows, conditions={"chatter_min_frequency_hz": 10.0, "max_chatter_power_ratio": 0.25})

    chattery = next(e for e in quality["episodes"] if e["episode_id"] == "chattery")
    clean = next(e for e in quality["episodes"] if e["episode_id"] == "clean")
    assert "actuator_chatter" in chattery["failure_labels"]
    assert chattery["verdict"] == "failed"
    assert clean["verdict"] in ("passed", "warning")
    assert clean["failure_labels"] == [] or "actuator_chatter" not in clean["failure_labels"]


def test_export_clean_dataset_removes_energy_explosion_episode():
    rows = _physics_rows(explosion_at=100) + _physics_rows()
    for row in rows[:200]:
        row["episode_id"] = "exploding"
    for row in rows[200:]:
        row["episode_id"] = "healthy"
    limits = {
        "joint_1_position": (-6.3, 6.3),
        "joint_1_velocity": (-10.0, 10.0),
        "joint_1_torque": (-200.0, 200.0),
    }

    clean_rows, report = export_clean_dataset(rows, robotics_limits=limits,
                                              conditions={"energy_anomaly_factor": 100.0})

    assert report["removed_episodes"] and report["removed_episodes"][0]["episode_id"] == "exploding"
    assert "energy_anomaly" in report["removed_episodes"][0]["failure_labels"]
    assert all(row["episode_id"] == "healthy" for row in clean_rows)
    assert len(clean_rows) == 200


# ── API contract ────────────────────────────────────────────────────────────────

def test_api_rejects_invalid_chatter_ratio(client):
    response = client.post("/v1/validate/physics-only", json={
        "data": _chirp_free_rows(),
        "simulation_type": "robotics",
        "conditions": {"max_chatter_power_ratio": 1.5},
    })
    assert response.status_code == 422


def test_api_accepts_dynamics_conditions_and_returns_checks(client):
    response = client.post("/v1/validate/physics-only", json={
        "data": _chirp_free_rows(chatter=True),
        "simulation_type": "robotics",
        "conditions": {"chatter_min_frequency_hz": 10.0, "max_chatter_power_ratio": 0.25},
    })
    assert response.status_code == 200
    body = response.json()
    names = [check["name"] for check in body["robotics_checks"]]
    assert "robotics_chatter:joint_1_velocity" in names
    chatter = next(c for c in body["robotics_checks"] if c["name"] == "robotics_chatter:joint_1_velocity")
    assert chatter["status"] == "failed"
