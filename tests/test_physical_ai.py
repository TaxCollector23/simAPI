"""Focused tests for Physical-AI episode, clock, action, and export helpers."""

import pytest

from core.physical_ai import (
    FAILURE_LABELS,
    action_state_consistency,
    check_stream_sync,
    episode_quality,
    export_clean_dataset,
)


def test_episode_quality_uses_fixed_label_vocabulary_per_episode():
    rows = [
        {"episode_id": "clean", "t": 0.0, "joint_1_position": 0.0},
        {"episode_id": "clean", "t": 0.1, "joint_1_position": 0.1},
        {"episode_id": "bad", "t": 0.0, "joint_1_position": 0.0},
        {"episode_id": "bad", "t": 0.1, "joint_1_position": 0.8},
    ]
    report = episode_quality(rows, {"joint_1_position": [-0.5, 0.5]})

    clean, bad = report["episodes"]
    assert report["verdict"] == "failed"
    assert clean["verdict"] == "passed"
    assert bad["verdict"] == "failed"
    assert bad["failure_labels"] == ["limit_violation"]
    assert set(bad["failure_labels"]).issubset(FAILURE_LABELS)
    assert bad["flagged_rows"] == [3]


def test_episode_quality_adds_saturation_and_frozen_sensor_labels():
    saturation = [{"t": i * 0.1, "joint_1_torque": 70.0} for i in range(4)]
    saturation_report = episode_quality(saturation, {"joint_1_torque": [-70.0, 70.0]})
    assert saturation_report["episodes"][0]["failure_labels"] == ["torque_saturation"]

    frozen = [
        {"t": i * 0.1, "joint_1_position": 0.2, "joint_2_position": i * 0.01}
        for i in range(6)
    ]
    frozen_report = episode_quality(frozen)
    assert frozen_report["episodes"][0]["failure_labels"] == ["frozen_sensor"]
    assert frozen_report["episodes"][0]["training_ready"] is False


def test_episode_quality_fails_closed_for_empty_rows():
    report = episode_quality([])
    assert report["verdict"] == "failed"
    assert report["summary"]["training_ready_episodes"] == 0
    assert "No rows" in report["detail"]


@pytest.mark.parametrize(
    "limits",
    [
        {"joint_1_position": [0.5, 0.5]},
        {"joint_1_position": [1, -1]},
        {"joint_1_position": [float("nan"), 1]},
        {"joint_1_position": [0, float("inf")]},
        {"joint_1_position": [0, 1, 2]},
    ],
)
def test_malformed_limits_raise_clear_signal_error(limits):
    with pytest.raises(ValueError, match="joint_1_position"):
        episode_quality([{"joint_1_position": 0.0}], limits)


def test_stream_sync_passes_aligned_streams_and_fails_offsets():
    aligned = check_stream_sync(
        {"camera": [0.0, 0.1, 0.2], "state": [0.01, 0.11, 0.21]}, 0.05
    )
    offset = check_stream_sync(
        {"camera": [0.0, 0.1, 0.2], "state": [0.2, 0.3, 0.4]}, 0.05
    )

    assert aligned["verdict"] == "passed"
    assert aligned["streams"]["state"]["median_offset_seconds"] == pytest.approx(0.01)
    assert offset["verdict"] == "failed"
    assert offset["streams"]["state"]["in_sync"] is False


def test_stream_sync_fails_mismatched_and_empty_lengths():
    mismatch = check_stream_sync({"camera": [0.0, 0.1, 0.2], "state": [0.0, 0.1]})
    empty = check_stream_sync({"camera": [0.0, 0.1], "state": []})

    assert mismatch["verdict"] == "failed"
    assert mismatch["streams"]["state"]["length_mismatch"] is True
    assert mismatch["streams"]["state"]["samples_compared"] == 2
    assert empty["verdict"] == "failed"
    assert empty["streams"]["state"]["length_mismatch"] is True
    assert empty["streams"]["state"]["samples_compared"] == 0


def test_stream_sync_never_passes_without_two_streams():
    report = check_stream_sync({"camera": []})

    assert report["verdict"] == "insufficient_data"
    assert report["in_sync"] is False


@pytest.mark.parametrize(
    "streams,tolerance",
    [
        ({"camera": [float("nan")], "state": [0.0]}, 0.05),
        ({"camera": [0.0], "state": [float("inf")]}, 0.05),
        ({"camera": [0.0], "state": [0.0]}, float("nan")),
        ({"camera": [0.0], "state": [0.0]}, -0.01),
    ],
)
def test_stream_sync_rejects_nonfinite_or_negative_inputs(streams, tolerance):
    with pytest.raises(ValueError):
        check_stream_sync(streams, tolerance)


def test_action_state_consistency_preserves_episode_boundaries_and_global_indices():
    rows = [
        {"episode_id": "a", "action": 1.0, "position": 0.0},
        {"episode_id": "b", "action": -1.0, "position": 10.0},
        {"episode_id": "a", "action": 1.0, "position": 1.0},
        {"episode_id": "b", "action": -1.0, "position": 9.0},
        {"episode_id": "a", "action": 1.0, "position": 0.5},
    ]
    report = action_state_consistency(rows, "action", "position")
    assert report["verdict"] == "failed"
    assert report["flagged_rows"] == [2]
    assert report["mismatches"] == [
        {"row": 2, "next_row": 4, "action": 1.0, "state_change": -0.5}
    ]


def test_action_state_consistency_rejects_invalid_tolerance():
    with pytest.raises(ValueError, match="tolerance"):
        action_state_consistency([], "action", "position", float("nan"))


def test_clean_export_removes_whole_failed_episodes_and_preserves_row_order():
    rows = [
        {"episode_id": "good", "t": 0.0, "joint_1_position": 0.0, "tag": "g0"},
        {"episode_id": "bad", "t": 0.0, "joint_1_position": 0.0, "tag": "b0"},
        {"episode_id": "good", "t": 0.1, "joint_1_position": 0.1, "tag": "g1"},
        {"episode_id": "bad", "t": 0.1, "joint_1_position": 0.8, "tag": "b1"},
    ]
    clean, report = export_clean_dataset(rows, {"joint_1_position": [-0.5, 0.5]})

    assert [row["tag"] for row in clean] == ["g0", "g1"]
    assert report["kept_episodes"] == ["good"]
    assert report["removed_episodes"] == [{
        "episode_id": "bad",
        "failure_labels": ["limit_violation"],
        "failed_checks": ["robotics_limit:joint_1_position"],
        "samples_removed": 2,
    }]


def test_clean_export_drops_failed_single_unnamed_episode():
    rows = [
        {"joint_1_position": 0.0},
        {"joint_1_position": 2.0},
    ]
    clean, report = export_clean_dataset(rows, {"joint_1_position": [-1.0, 1.0]})
    assert clean == []
    assert report["rows_out"] == 0
    assert report["removed_episodes"][0]["episode_id"] == "Episode 1"


def test_unprofiled_screening_warning_caps_episode_and_dataset_readiness():
    report = episode_quality([{"episode_id": "unprofiled", "joint_1_torque": 25.0}])

    episode = report["episodes"][0]
    assert episode["verdict"] == "warning"
    assert episode["training_ready"] is False
    assert report["verdict"] == "warning"
    assert report["summary"]["training_ready_episodes"] == 0
    assert report["summary"]["removed_episodes"] == 1


def test_other_unrelated_engine_warnings_do_not_change_physical_ai_verdict():
    report = episode_quality([{"episode_id": "no_joint_signal", "temperature": 25.0}])

    episode = report["episodes"][0]
    assert episode["verdict"] == "passed"
    assert episode["training_ready"] is True
    assert report["verdict"] == "passed"
