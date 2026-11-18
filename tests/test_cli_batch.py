"""Streaming batch CLI (simapi validate-batch) end-to-end tests."""

import json
from pathlib import Path

import pandas as pd
import pytest

from cli import main

pytest.importorskip("pyarrow", reason="batch parquet path needs pyarrow")

LIMITS = '{"joint_1_velocity": [-10.0, 10.0], "joint_1_torque": [-200.0, 200.0]}'
CONDITIONS = '{"energy_anomaly_factor": 100.0}'


def _rows(episode: str, explosion: bool = False):
    import numpy as np

    dt = 0.01
    n = 64
    t = np.arange(n) * dt
    v = 0.5 * np.sin(2 * np.pi * 0.5 * t)
    tau = 0.5 * np.gradient(v, dt)
    if explosion:
        v[n // 2] += 6.0
    return pd.DataFrame({
        "episode_id": episode, "time": t,
        "joint_1_position": np.cumsum(v) * dt,
        "joint_1_velocity": v, "joint_1_torque": tau,
    })


@pytest.fixture()
def dataset(tmp_path: Path) -> Path:
    _rows("good_a").to_parquet(tmp_path / "good_a.parquet")
    (tmp_path / "shards").mkdir()
    _rows("good_b").to_parquet(tmp_path / "shards" / "good_b.parquet")
    _rows("exploding", explosion=True).to_csv(tmp_path / "bad.csv", index=False)
    return tmp_path


def _summary(out: Path) -> dict:
    return json.loads((out / "dataset_summary.json").read_text())


def test_batch_passes_clean_dataset(dataset: Path, tmp_path: Path):
    clean = tmp_path / "clean_only"
    (clean / "shards").mkdir(parents=True)
    _rows("good_a").to_parquet(clean / "good_a.parquet")
    _rows("good_b").to_parquet(clean / "shards" / "good_b.parquet")
    out = tmp_path / "out1"
    code = main(["validate-batch", str(clean), "--out", str(out), "--workers", "2",
                 "--limits", LIMITS])
    summary = _summary(out)
    assert code == 0
    assert summary["verdict"] == "passed"
    assert summary["episodes_passed"] == 2 and summary["episodes_failed"] == 0
    assert (out / "QUALITY_CARD.md").exists()
    assert "Episodes passed" in (out / "QUALITY_CARD.md").read_text()


def test_batch_flags_bad_episode_and_fails_closed(dataset: Path, tmp_path: Path):
    out = tmp_path / "out2"
    code = main(["validate-batch", str(dataset), "--out", str(out), "--workers", "2",
                 "--limits", LIMITS, "--conditions", CONDITIONS])
    summary = _summary(out)
    assert code == 1
    assert summary["verdict"] == "failed"
    by_id = {e["episode_id"]: e["verdict"] for e in summary["episodes"]}
    assert by_id["exploding"] == "failed"
    assert by_id["good_a"] == "passed" and by_id["good_b"] == "passed"
    assert "robotics_energy:joint_1" in summary["failed_checks"]


def test_batch_fails_closed_on_unreadable_file(tmp_path: Path):
    broken = tmp_path / "broken.csv"
    broken.write_text("time,episode_id,garbage\n0.0,e1,x\n")
    out = tmp_path / "out3"
    code = main(["validate-batch", str(broken), "--out", str(out), "--workers", "1",
                 "--limits", LIMITS])
    summary = _summary(out)
    assert code == 1
    # The file parses, but the configured joint limits are missing — the run
    # must fail closed, never silently pass.
    assert "robotics_limit:joint_1_velocity" in summary["failed_checks"]


def test_batch_rejects_malformed_conditions(tmp_path: Path):
    (tmp_path / "good.parquet").write_bytes(b"PAR1")
    with pytest.raises(SystemExit, match="not valid JSON"):
        main(["validate-batch", str(tmp_path), "--conditions", '{"max_time_step": '])
