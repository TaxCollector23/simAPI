"""Upgraded dynamics suites: 15 Hz chatter floor, sliding-window energy fit
with low-excitation guard, and the humanoid contact suite."""

import numpy as np
import pandas as pd

from core.robotics_validation import check_robotics_limits

DT = 0.002  # 500 Hz simulation log


def _rows_500hz(n=1500, chatter_hz=None):
    """Smooth 1 Hz joint motion, optionally with a gated oscillation."""
    times = np.arange(n) * DT
    velocity = np.sin(2.0 * np.pi * 1.0 * times)
    if chatter_hz is not None:
        gate = (np.arange(n) >= n // 2).astype(float)
        velocity = velocity + 1.5 * gate * np.sin(2.0 * np.pi * chatter_hz * times)
    return [
        {"episode_id": "run", "time": float(t),
         "joint_1_position": float(v) * DT, "joint_1_velocity": float(v)}
        for t, v in zip(times, velocity, strict=True)
    ]


def _physics_rows(n=300, explosion_at=None, inertia_drift=False):
    """Self-consistent physics: effort = I(t)*acceleration + gravity torque."""
    dt = 0.01
    times = np.arange(n) * dt
    velocity = 0.5 * np.sin(2.0 * np.pi * 0.5 * times)
    acceleration = np.gradient(velocity, dt)
    inertia = 0.5 + (times / times[-1]) * 1.5 if inertia_drift else np.full(n, 0.5)
    effort = inertia * acceleration + 0.2
    if explosion_at is not None:
        velocity[explosion_at] += 6.0  # energy injected by nothing
    return [
        {"episode_id": "run", "time": float(t), "joint_1_position": 0.0,
         "joint_1_velocity": float(v), "joint_1_torque": float(e)}
        for t, v, e in zip(times, velocity, effort, strict=True)
    ]


def _report(rows, conditions):
    return check_robotics_limits(pd.DataFrame(rows), conditions=conditions, source_rows=rows)


def _check(report, name):
    return next(c for c in report["checks"] if c["name"] == name)


# ── Chatter: fixed 15 Hz physical floor ────────────────────────────────────────

def test_35hz_chatter_on_500hz_log_is_flagged_with_default_floor():
    # 500 Hz Nyquist is 250 Hz; the old Nyquist/2 default (125 Hz) missed 35 Hz.
    report = _report(_rows_500hz(chatter_hz=35.0), {"max_chatter_power_ratio": 0.25})
    check = _check(report, "robotics_chatter:joint_1_velocity")
    assert check["status"] == "failed"
    assert check["indices"], "35 Hz chatter must flag its samples"
    # Only windows overlapping the gated second half can flag; the first
    # fully-clean window (0-200) must stay out of the flagged set.
    assert min(check["indices"]) >= 500


def test_default_chatter_floor_is_15_hz():
    report = _report(_rows_500hz(), {"max_chatter_power_ratio": 0.25})
    assert report["summary"]["actuator_chatter"]["min_frequency_hz"] == 15.0
    assert _check(report, "robotics_chatter:joint_1_velocity")["status"] == "passed"


def test_5hz_content_below_default_floor_is_not_flagged():
    report = _report(_rows_500hz(chatter_hz=5.0), {"max_chatter_power_ratio": 0.25})
    assert _check(report, "robotics_chatter:joint_1_velocity")["status"] == "passed"


def test_chatter_floor_remains_configurable():
    report = _report(_rows_500hz(chatter_hz=5.0),
                     {"max_chatter_power_ratio": 0.25, "chatter_min_frequency_hz": 3.0})
    check = _check(report, "robotics_chatter:joint_1_velocity")
    assert check["status"] == "failed"


# ── Energy: sliding 32-step windows with variance guard ────────────────────────

def test_energy_flags_local_injection_with_sliding_windows():
    report = _report(_physics_rows(explosion_at=150), {"energy_anomaly_factor": 100.0})
    check = _check(report, "robotics_energy:joint_1")
    assert check["status"] == "failed"
    assert 150 in check["indices"]


def test_drifting_inertia_without_anomaly_still_passes():
    # Posture-dependent inertia drift must not be read as an energy anomaly.
    report = _report(_physics_rows(inertia_drift=True), {"energy_anomaly_factor": 100.0})
    assert _check(report, "robotics_energy:joint_1")["status"] == "passed"


def test_low_excitation_window_is_not_evaluated():
    # Constant velocity + zero effort: kinetic energy never changes, so the
    # work/energy regression has nothing to explain -> fail-closed warning.
    n = 100
    rows = [
        {"episode_id": "run", "time": i * 0.01, "joint_1_position": 0.0,
         "joint_1_velocity": 0.5, "joint_1_torque": 0.0}
        for i in range(n)
    ]
    report = _report(rows, {"energy_anomaly_factor": 100.0})
    check = _check(report, "robotics_energy:joint_1")
    assert check["status"] == "warning"
    assert "low_excitation" in check["detail"]


def test_clean_physics_passes_sliding_energy_check():
    report = _report(_physics_rows(), {"energy_anomaly_factor": 100.0})
    assert _check(report, "robotics_energy:joint_1")["status"] == "passed"


# ── Humanoid contact suite ─────────────────────────────────────────────────────

def _foot_rows(slip_speed=0.5, force=50.0, n=40):
    return [
        {"episode_id": "walk", "time": i * 0.02,
         "left_foot_contact_force_z": force,
         "left_foot_linear_velocity_x": slip_speed,
         "left_foot_linear_velocity_y": 0.0}
        for i in range(n)
    ]


def test_foot_slip_is_flagged():
    report = _report(_foot_rows(slip_speed=0.5, force=50.0), {"max_foot_slip_ms": 0.1})
    check = _check(report, "robotics_foot_slip:left_foot")
    assert check["status"] == "failed"
    assert check["violations"] == 40
    assert any("sliding" in reason for reasons in report["excluded"].values() for reason in reasons)


def test_unloaded_foot_moving_fast_is_not_slip():
    # Below the default 1 N contact threshold the foot is in swing phase.
    report = _report(_foot_rows(slip_speed=0.5, force=0.5), {"max_foot_slip_ms": 0.1})
    assert _check(report, "robotics_foot_slip:left_foot")["status"] == "passed"


def test_loaded_stationary_foot_passes():
    report = _report(_foot_rows(slip_speed=0.01, force=50.0), {"max_foot_slip_ms": 0.1})
    assert _check(report, "robotics_foot_slip:left_foot")["status"] == "passed"


def test_foot_slip_warns_without_foot_signals():
    rows = [{"episode_id": "walk", "time": i * 0.02, "joint_1_position": 0.1}
            for i in range(20)]
    report = _report(rows, {"max_foot_slip_ms": 0.1})
    check = _check(report, "robotics_foot_slip:not_evaluated")
    assert check["status"] == "warning"


def _skew_rows(skew_seconds=0.02, n=30):
    return [
        {"episode_id": "walk", "time": i * 0.02,
         "t_joint": i * 0.02, "t_cam": i * 0.02 + skew_seconds}
        for i in range(n)
    ]


def test_camera_joint_timestamp_skew_is_flagged():
    report = _report(_skew_rows(skew_seconds=0.02), {"max_sync_skew_ms": 10.0})
    check = _check(report, "robotics_stream_skew:camera_joint")
    assert check["status"] == "failed"
    assert check["violations"] == 30  # 20 ms constant offset > 10 ms budget


def test_small_timestamp_skew_passes():
    report = _report(_skew_rows(skew_seconds=0.002), {"max_sync_skew_ms": 10.0})
    assert _check(report, "robotics_stream_skew:camera_joint")["status"] == "passed"


def test_skew_warns_without_timestamp_columns():
    rows = [{"episode_id": "walk", "time": i * 0.02} for i in range(20)]
    report = _report(rows, {"max_sync_skew_ms": 5.0})
    check = _check(report, "robotics_stream_skew:not_evaluated")
    assert check["status"] == "warning"


def test_contact_suite_is_opt_in():
    report = _report(_foot_rows() + _skew_rows(), {})
    assert not any(c["name"].startswith(("robotics_foot_slip", "robotics_stream_skew"))
                   for c in report["checks"])


def test_negative_slip_or_skew_budgets_are_rejected():
    report = _report(_foot_rows(), {"max_foot_slip_ms": -0.1})
    assert _check(report, "robotics_foot_slip:not_evaluated")["status"] == "warning"
    report = _report(_skew_rows(), {"max_sync_skew_ms": -1.0})
    assert _check(report, "robotics_stream_skew:not_evaluated")["status"] == "warning"
