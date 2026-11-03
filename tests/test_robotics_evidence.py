"""Evidence must describe the values that actually drove a robotics failure."""
import pandas as pd

from core.robotics_validation import check_robotics_limits


def test_derived_evidence_uses_interval_motion_and_episode_local_previous_sample():
    rows = [
        {"episode_id": "a", "time": 0, "joint_1_position": 0},
        {"episode_id": "a", "time": 0.1, "joint_1_position": 1},
        {"episode_id": "b", "time": 0, "joint_1_position": 0},
        {"episode_id": "b", "time": 0.1, "joint_1_position": 0.01},
    ]
    result = check_robotics_limits(pd.DataFrame(rows), {"joint_1_velocity": (-2, 2)}, rows)
    evidence = result["evidence"]["entries"]
    derived = next(e for e in evidence if e["check"] == "robotics_derived_limit:joint_1_velocity")
    assert derived["observed"] == 10
    assert derived["episode_id"] == "a"
    assert derived["sample_index"] == 1
    assert derived["time"] == 0.1
    assert derived["expected"] == [-2, 2]


def test_bound_evidence_distinguishes_missing_from_zero():
    rows = [{"time": 0, "joint_1_position": 0}, {"time": 1, "joint_1_position": None}]
    result = check_robotics_limits(pd.DataFrame(rows), {"joint_1_position": (-1, 1)}, rows)
    evidence = result["evidence"]["entries"]
    assert len(evidence) == 1
    assert evidence[0]["observed"] is None
    assert evidence[0]["sample_index"] == 1


def test_evidence_cap_keeps_total_findings_explicit():
    rows = [{"time": i, "joint_1_position": 2} for i in range(1001)]
    result = check_robotics_limits(pd.DataFrame(rows), {"joint_1_position": (-1, 1)}, rows)
    assert result["evidence"]["total"] == 1001
    assert result["evidence"]["truncated"] is True
    assert len(result["evidence"]["entries"]) == 1000
