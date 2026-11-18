"""Upgraded Physical AI checks: action-state causality/lag, dead-episode
filter, stall-torque filter, and their wiring into export_clean_dataset."""

import math

import pytest

from core.physical_ai import (
    action_state_causality,
    episode_quality,
    export_clean_dataset,
)

DT = 0.02


def _causal_rows(episode="e1", n=60, state_shift=0):
    """A healthy recording: action[t] accelerates the joint at t+1.

    state_shift=1 delays the recorded state stream by one frame (the
    classic off-by-one recorder bug).
    """
    rows = []
    pos, vel = 0.0, 0.0
    for t in range(n):
        action = math.sin(t * 0.3)
        rows.append({"episode_id": episode, "time": t * DT,
                     "action": action, "joint_1_position": pos})
        vel += action * DT
        pos += vel * DT
    if state_shift:
        shifted = [dict(r) for r in rows]
        for t in range(n):
            shifted[t]["joint_1_position"] = rows[t - state_shift]["joint_1_position"] if t >= state_shift else 0.0
        return shifted
    return rows


def test_healthy_recording_is_causal_at_lag_1():
    result = action_state_causality(_causal_rows(), "action", "joint_1_position")
    assert result["verdict"] == "passed"
    assert result["reason"] == "causal_at_lag_1"
    assert result["best_lag"] == 1
    assert result["correlations_by_lag"][1] > 0.9


def test_off_by_one_state_stream_is_detected():
    result = action_state_causality(_causal_rows(state_shift=1), "action", "joint_1_position")
    assert result["verdict"] == "failed"
    assert result["reason"] == "lag_mismatch"
    assert result["best_lag"] == 2
    assert "shifted by 1 frame" in result["detail"]


def test_uncorrelated_action_is_no_causality():
    # The state stream is driven by a different signal than the actions.
    rows = []
    pos, vel = 0.0, 0.0
    for t in range(80):
        action = math.sin(t * 0.9)
        rows.append({"episode_id": "e", "time": t * DT,
                     "action": action, "joint_1_position": pos})
        vel += math.cos(t * 0.13) * DT  # unrelated driver
        pos += vel * DT
    result = action_state_causality(rows, "action", "joint_1_position")
    assert result["verdict"] == "failed"
    assert result["reason"] == "no_causality"


def test_causality_needs_enough_samples():
    result = action_state_causality(_causal_rows(n=3), "action", "joint_1_position")
    assert result["verdict"] == "warning"
    assert result["reason"] == "insufficient_data"


def test_causality_rejects_bad_params():
    rows = _causal_rows()
    with pytest.raises(ValueError):
        action_state_causality(rows, "action", "joint_1_position", max_lag=0)
    with pytest.raises(ValueError):
        action_state_causality(rows, "action", "joint_1_position", min_correlation=2.0)


def _limits():
    return {"joint_1_position": (-10, 10), "joint_1_velocity": (-10, 10),
            "joint_1_torque": (-70, 70)}


def _dead_rows(n=50):
    return [{"episode_id": "dead", "time": i * DT,
             "joint_1_position": 0.5, "joint_1_velocity": 0.0,
             "joint_1_torque": 0.0} for i in range(n)]


def _live_rows(n=50):
    return [{"episode_id": "live", "time": i * DT,
             "joint_1_position": 0.05 * i, "joint_1_velocity": 0.5,
             "joint_1_torque": 1.0} for i in range(n)]


def test_dead_episode_is_flagged_but_live_is_not():
    quality = episode_quality(_dead_rows() + _live_rows(), _limits(),
                              min_active_motion_ratio=0.5)
    by_id = {e["episode_id"]: e for e in quality["episodes"]}
    assert by_id["dead"]["failure_labels"] == ["dead_episode"]
    assert by_id["dead"]["training_ready"] is False
    assert by_id["live"]["training_ready"] is True


def test_dead_filter_is_opt_in():
    quality = episode_quality(_dead_rows(), _limits())
    assert "dead_episode" not in quality["episodes"][0]["failure_labels"]


def test_stall_torque_is_flagged():
    # 4 s of 60 Nm (86% of the 70 Nm limit) against a frozen joint.
    rows = [{"episode_id": "stall", "time": i * 0.02,
             "joint_1_position": 0.3, "joint_1_torque": 60.0} for i in range(200)]
    quality = episode_quality(rows, _limits(), max_stall_duration_s=1.0)
    assert "stall_torque" in quality["episodes"][0]["failure_labels"]


def test_brief_high_torque_is_not_a_stall():
    rows = [{"episode_id": "brief", "time": i * 0.02,
             "joint_1_position": 0.3, "joint_1_torque": 60.0} for i in range(20)]  # 0.4 s
    quality = episode_quality(rows, _limits(), max_stall_duration_s=1.0)
    assert "stall_torque" not in quality["episodes"][0]["failure_labels"]


def test_moving_joint_with_high_torque_is_not_a_stall():
    rows = [{"episode_id": "moving", "time": i * 0.02,
             "joint_1_position": 0.01 * i, "joint_1_torque": 60.0} for i in range(200)]
    quality = episode_quality(rows, _limits(), max_stall_duration_s=1.0)
    assert "stall_torque" not in quality["episodes"][0]["failure_labels"]


def test_filter_params_are_validated():
    with pytest.raises(ValueError):
        episode_quality(_live_rows(), _limits(), min_active_motion_ratio=1.5)
    with pytest.raises(ValueError):
        episode_quality(_live_rows(), _limits(), max_stall_duration_s=0.0)
    with pytest.raises(ValueError):
        episode_quality(_live_rows(), _limits(), stall_torque_fraction=0.0)


def test_export_clean_dataset_removes_dead_and_stalled_episodes():
    stall = [{"episode_id": "stall", "time": i * 0.02,
              "joint_1_position": 0.3, "joint_1_torque": 60.0} for i in range(200)]
    clean, report = export_clean_dataset(
        _dead_rows() + _live_rows() + stall, _limits(),
        min_active_motion_ratio=0.5, max_stall_duration_s=1.0,
    )
    assert report["kept_episodes"] == ["live"]
    removed = {e["episode_id"]: e["failure_labels"] for e in report["removed_episodes"]}
    assert "dead_episode" in removed["dead"]
    assert "stall_torque" in removed["stall"]
    assert all(row["episode_id"] == "live" for row in clean)
    assert report["rows_out"] == len(_live_rows())


def test_new_labels_are_in_the_failure_vocabulary():
    from core.physical_ai import FAILURE_LABELS
    for label in ("foot_slip", "timestamp_skew", "workspace_floor_violation",
                  "self_collision", "dead_episode", "stall_torque"):
        assert label in FAILURE_LABELS
