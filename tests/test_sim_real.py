"""Tests for the sim-versus-real distribution comparison."""

import numpy as np
import pandas as pd
import pytest

from core.sim_real import compare_sim_real


def _trajectory(scale: float, n: int = 80) -> pd.DataFrame:
    time = np.arange(n, dtype=float) * 0.01
    position = scale * time
    return pd.DataFrame({
        "episode_id": "episode-1",
        "t": time,
        "joint_1_position": position,
        "joint_1_velocity": np.full(n, scale),
        "joint_1_torque": np.sin(time) * scale,
    })


def test_three_times_faster_sim_trajectory_flags_derived_velocity_drift():
    report = compare_sim_real(_trajectory(3.0), _trajectory(1.0))
    signal = report["signals"]["joint_1_velocity_fd"]
    assert signal["sim"]["mean"] == pytest.approx(3.0)
    assert signal["real"]["mean"] == pytest.approx(1.0)
    assert signal["overlap"] < 0.5
    assert signal["drift"] is True
    assert report["verdict"] == "drift_detected"


def test_identical_rows_are_aligned_with_full_signal_overlap():
    data = _trajectory(1.25)
    report = compare_sim_real(data, data.copy())
    assert report["verdict"] == "aligned"
    assert report["signals_only_in_sim"] == []
    assert report["signals_only_in_real"] == []
    assert all(signal["overlap"] == 1.0 and not signal["drift"]
               for signal in report["signals"].values())


def test_signals_available_on_only_one_side_are_listed():
    sim_data = _trajectory(1.0)
    real_data = sim_data.drop(columns="joint_1_torque")
    report = compare_sim_real(sim_data, real_data)
    assert report["signals_only_in_sim"] == ["joint_1_torque"]
    assert report["signals_only_in_real"] == []


def test_check_passing_only_on_one_side_is_reported_and_changes_verdict():
    sim_report = {
        "status": "passed",
        "training_ready": True,
        "checks": [{"name": "robotics_limit:joint_1_torque", "status": "passed"}],
    }
    real_report = {
        "status": "failed",
        "training_ready": False,
        "excluded": {3: ["torque out of bounds"]},
        "checks": [{"name": "robotics_limit:joint_1_torque", "status": "failed"}],
    }
    report = compare_sim_real(_trajectory(1.0), _trajectory(1.0), sim_report, real_report)
    assert report["check_pass_rates"] == {
        "robotics_limit:joint_1_torque": {"sim": True, "real": False}
    }
    assert report["sim"]["checks_passed"] == report["sim"]["checks_total"] == 1
    assert report["real"]["excluded_count"] == 1
    assert report["verdict"] == "drift_detected"
