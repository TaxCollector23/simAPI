"""Local (air-gapped) SDK mode and the inline quarantine watcher."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk"))

from simapi import SimAPI, SimAPIWatcher  # noqa: E402


def _good_rows(n=60):
    return [{"time": i * 0.02, "joint_1_position": 0.05 * i,
             "joint_1_velocity": 0.5, "joint_1_torque": 3.0} for i in range(n)]


def _bad_rows(n=10):
    return [{"time": i * 0.02, "joint_1_position": 99.0,
             "joint_1_velocity": 900.0, "joint_1_torque": 3.0} for i in range(n)]


LIMITS = {"joint_1_position": (-10, 10), "joint_1_velocity": (-10, 10),
          "joint_1_torque": (-70, 70)}


def test_local_mode_validates_in_process_without_http():
    client = SimAPI(mode="local")
    result = client.validate(_good_rows(), simulation_type="robotics",
                             robotics_limits=LIMITS)
    assert result.status == "passed"
    assert result.trials_submitted == 60
    assert result.trials_valid == 60
    assert result.training_ready is True
    assert result.job_id.startswith("local-")
    assert result.physics_checks  # the engine's checks are surfaced


def test_local_mode_flags_limit_violations():
    client = SimAPI(mode="local")
    result = client.validate(_bad_rows(), simulation_type="robotics",
                             robotics_limits=LIMITS)
    assert result.status == "failed"
    assert result.trials_excluded > 0
    assert result.training_ready is False
    assert any(c.status == "failed" for c in result.physics_checks)


def test_local_mode_accepts_dataframe_and_custom_job_id():
    client = SimAPI(mode="local")
    result = client.validate(pd.DataFrame(_good_rows()), simulation_type="robotics",
                             robotics_limits=LIMITS, job_id="nightly-42")
    assert result.status == "passed"
    assert result.job_id == "nightly-42"


def test_local_mode_rejects_non_robotics_types():
    client = SimAPI(mode="local")
    with pytest.raises(ValueError, match="robotics"):
        client.validate(_good_rows(), simulation_type="aerodynamics")


def test_local_mode_health():
    assert SimAPI(mode="local").health()["status"] == "ok"


def test_invalid_mode_is_rejected():
    with pytest.raises(ValueError):
        SimAPI(mode="offline")


# ── SimAPIWatcher ──────────────────────────────────────────────────────────────

def _batch_frame():
    rows = []
    for i in range(80):
        rows.append({"episode_id": "good", "time": i * 0.02,
                     "joint_1_position": 0.05 * i, "joint_1_velocity": 0.5,
                     "joint_1_torque": 3.0})
    for i in range(80):
        rows.append({"episode_id": "bad", "time": i * 0.02,
                     "joint_1_position": 0.05 * i, "joint_1_velocity": 0.5,
                     "joint_1_torque": 3.0})
    # Corrupt one sample of "bad": a teleport.
    rows[-1]["joint_1_velocity"] = 900.0
    return pd.DataFrame(rows)


def test_watcher_quarantines_bad_episodes_and_writes_heatmap(tmp_path):
    batch = tmp_path / "batch.parquet"
    _batch_frame().to_parquet(batch)
    quarantine = tmp_path / "quarantine"

    with SimAPIWatcher({"robotics_limits": LIMITS}, quarantine) as watcher:
        summary = watcher.process_batch(batch)

    assert summary["episodes"] == 2
    assert summary["quarantined"] == 1
    assert summary["clean"] == 1
    assert summary["rows_quarantined"] == 80

    quarantined_file = quarantine / "episode_bad.parquet"
    assert quarantined_file.exists()
    quarantined = pd.read_parquet(quarantined_file)
    assert set(quarantined["episode_id"]) == {"bad"}
    assert len(summary["clean_dataframe"]) == 80
    assert set(summary["clean_dataframe"]["episode_id"]) == {"good"}

    heatmap_path = quarantine / "sim_bug_heatmap.json"
    assert heatmap_path.exists()
    heatmap = json.loads(heatmap_path.read_text())
    assert heatmap["batches_processed"] == 1
    ranked = heatmap["ranked_failure_causes"]
    assert ranked, "the teleport must appear as a ranked cause"
    assert "teleport" in ranked or "limit_violation" in ranked


def test_watcher_clean_batch_quarantines_nothing(tmp_path):
    batch = tmp_path / "clean.parquet"
    frame = _batch_frame()
    frame = frame[frame["episode_id"] == "good"]
    frame.to_parquet(batch)

    with SimAPIWatcher({"robotics_limits": LIMITS}, tmp_path / "q") as watcher:
        summary = watcher.process_batch(batch)

    assert summary["quarantined"] == 0
    assert not list((tmp_path / "q").glob("episode_*.parquet"))


def test_watcher_rejects_batch_without_episode_column(tmp_path):
    batch = tmp_path / "noep.parquet"
    pd.DataFrame({"time": [0.0, 0.02], "joint_1_position": [0.0, 0.1]}).to_parquet(batch)
    with SimAPIWatcher({"robotics_limits": LIMITS}, tmp_path / "q") as watcher:
        with pytest.raises(ValueError, match="episode"):
            watcher.process_batch(batch)


def test_watcher_heatmap_ranks_worst_cause_first(tmp_path):
    batch = tmp_path / "batch.parquet"
    rows = []
    # Two episodes with different failure counts.
    for i in range(60):
        rows.append({"episode_id": "limit_only", "time": i * 0.02,
                     "joint_1_position": 99.0, "joint_1_velocity": 0.5,
                     "joint_1_torque": 3.0})
    for i in range(60):
        rows.append({"episode_id": "limit_and_teleport", "time": i * 0.02,
                     "joint_1_position": 99.0, "joint_1_velocity": 900.0 if i == 30 else 0.5,
                     "joint_1_torque": 3.0})
    pd.DataFrame(rows).to_parquet(batch)

    with SimAPIWatcher({"robotics_limits": LIMITS}, tmp_path / "q") as watcher:
        watcher.process_batch(batch)
        ranked = watcher.heatmap()

    counts = [entry["episodes"] for entry in ranked.values()]
    assert counts == sorted(counts, reverse=True)
