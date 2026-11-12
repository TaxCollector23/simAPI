"""Regression tests for episode-aware checks and physical-robot data adapters."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from core.apie import AdaptivePhysicsIntelligenceEngine, FilterBank, TestPlan
from core.dimensional.dimensions import BASE_DIMENSIONS
from core.dimensional.engine import validate as dimensional_validate
from core.dimensional.units_resolver import resolve_units
from core.ingestion import DataIngester
from core.report_export import to_junit_xml, to_sarif
from core.training_data_card import build_training_data_card
from integrations.lerobot_loader import load_lerobot
from integrations.ros2_loader import load_rosbag2

TestPlan.__test__ = False


@pytest.fixture()
def no_report_rate_limit():
    from api import server

    previous = server.app.dependency_overrides.get(server.caller_identity)
    server.app.dependency_overrides[server.caller_identity] = lambda: "robotics-report-test"
    yield
    if previous is None:
        server.app.dependency_overrides.pop(server.caller_identity, None)
    else:
        server.app.dependency_overrides[server.caller_identity] = previous


def _robot_episodes(n_episodes: int = 16, rows_per_episode: int = 14) -> pd.DataFrame:
    rng = np.random.default_rng(4)
    rows = []
    for episode in range(n_episodes):
        phase = rng.uniform(-np.pi, np.pi)
        for time_value in np.linspace(0.0, 1.0, rows_per_episode):
            rows.append({
                "episode_id": episode,
                "t": time_value,
                "q1": 0.5 * np.sin(3 * time_value + phase),
                "dq1": 1.5 * np.cos(3 * time_value + phase),
                "tau1": 0.2 * np.cos(3 * time_value + phase),
            })
    return pd.DataFrame(rows)


def _temporal_plan(columns: list[str]) -> TestPlan:
    return TestPlan(
        checks=[{"check": "temporal_coherence", "priority": 1,
                 "params": {"columns": columns, "threshold_sigma": 7.0}}],
        target_columns=[], feature_columns=[], suspected_corruption_types={},
        ensemble_threshold_sigma=7.0, ratio_threshold_sigma=7.0,
        ai_diagnosis="", ai_used=False,
    )


def test_episode_boundaries_are_not_temporal_spikes_and_mid_episode_spike_is_caught():
    data = _robot_episodes()
    clean_exclusions, _ = FilterBank(data, _temporal_plan(["q1", "dq1", "tau1"])).run()
    assert clean_exclusions == set()
    apie_result = AdaptivePhysicsIntelligenceEngine().validate(data.copy(), domain="robotics")
    assert not apie_result.excluded_indices

    corrupted = data.copy()
    spike_index = 7 * 14 + 6
    corrupted.loc[spike_index, "tau1"] += 25
    exclusions, scores = FilterBank(
        corrupted, _temporal_plan(["q1", "dq1", "tau1"])
    ).run()
    assert spike_index in exclusions
    assert any(score.corruption_type == "solver_divergence" for score in scores)


def test_api_engine_recognizes_t_and_does_not_downgrade_unavailable_checks(client):
    rows = _robot_episodes(4, 12).to_dict(orient="records")
    response = client.post("/v1/validate", json={"data": rows, "simulation_type": "robotics"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["robotics_summary"]["time_column"] == "t"
    assert body["training_ready"] is True
    assert not body["trials_excluded"]
    assert all(issue["status"] != "warning" for issue in body["issues"]
               if "not evaluated" in str(issue.get("detail", "")).lower())


def test_bare_t_is_time_but_uppercase_T_remains_temperature():
    frame, _ = DataIngester().ingest([{"t": 0.2, "T": 300.0, "joint_1_position": 0.1}])
    assert "t" in frame.columns
    assert "temperature" in frame.columns
    units = resolve_units(["t", "temperature"])
    assert units.columns["t"].dimension == BASE_DIMENSIONS["time"]
    assert units.columns["temperature"].dimension == BASE_DIMENSIONS["temperature"]


def test_multivalued_surface_is_demoted_but_single_valued_corruption_is_still_found():
    rng = np.random.default_rng(12)
    velocity = rng.uniform(1.0, 45.0, 400)
    density = rng.uniform(0.5, 2.0, 400)
    hidden_size = rng.choice([0.01, 0.05, 0.2], 400)
    data = pd.DataFrame({
        "velocity": velocity,
        "density": density,
        "drag_force": 0.5 * density * velocity**2 * hidden_size
        * (1.0 + rng.normal(0.0, 0.01, 400)),
    })
    report = dimensional_validate(data)
    demoted = report.surface_diagnostics.get("demoted_targets", [])
    drag_demotions = [finding for finding in demoted if finding["column"] == "drag_force"]
    assert drag_demotions and all(finding["gate"] == "multi_valued_physics" for finding in drag_demotions)
    assert not any(finding.layer == "response_surface" for finding in report.row_findings)

    data["drag_force"] = 0.5 * density * velocity**2 * 0.05
    corruption = rng.choice(len(data), 12, replace=False)
    data.loc[corruption, "drag_force"] *= 8.0
    report = dimensional_validate(data)
    assert "drag_force" not in {
        finding["column"] for finding in report.surface_diagnostics.get("demoted_targets", [])
    }
    assert any(finding.layer == "response_surface" for finding in report.row_findings)


def test_report_formats_are_deterministic_and_warning_gate_is_configurable():
    result = {
        "job_id": "robot-run",
        "status": "warning",
        "training_ready": False,
        "trials_submitted": 3,
        "trials_excluded": 0,
        "processing_ms": 12.5,
        "issues": [{
            "name": "robotics_gap", "human_name": "Sampling gap", "status": "warning",
            "description": "Large interval", "detail": "One interval exceeds the limit.",
            "category": "robotics_limits",
        }],
    }
    junit = to_junit_xml(result)
    assert 'failures="0"' in junit
    assert "WARNING:" in junit
    assert 'failures="2"' in to_junit_xml(result, strict_warnings=True)
    sarif = to_sarif(result)
    assert sarif["version"] == "2.1.0"
    assert any(item["level"] == "warning" for item in sarif["runs"][0]["results"])

    card = build_training_data_card({**result, "surface_diagnostics": {"demoted_targets": [{
        "column": "joint_1_torque", "gate": "multi_valued_physics",
        "reason": "Nearby states disagree on torque.",
    }]}})
    assert "Nearby states disagree on torque." in card
    assert "not applied" in card

    excluded = {**result, "status": "failed", "training_ready": False,
                "excluded_indices": [1], "trials_excluded": 0}
    assert 'failures="1"' in to_junit_xml(excluded)


def test_report_endpoint_returns_junit_xml(client, no_report_rate_limit):
    response = client.post(
        "/v1/validate/report?format=junit",
        json={"data": _robot_episodes(2, 8).to_dict(orient="records"),
              "simulation_type": "robotics", "run_ai": True},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/xml")
    assert response.text.startswith("<?xml")


@pytest.mark.parametrize(
    ("query", "content_type", "expected"),
    [
        ("format=sarif", "application/json", '"version":"2.1.0"'),
        ("format=card&dataset_name=robot_run", "text/markdown", "Training Data Card: robot_run"),
    ],
)
def test_report_endpoint_supports_sarif_and_data_card(client, no_report_rate_limit, query, content_type, expected):
    response = client.post(
        f"/v1/validate/report?{query}",
        json={"data": _robot_episodes(2, 8).to_dict(orient="records"),
              "simulation_type": "robotics", "run_ai": False},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(content_type)
    if expected.startswith('"'):
        assert expected in response.text.replace(" ", "")
    else:
        assert expected in response.text


def test_report_endpoint_rejects_unknown_format(client, no_report_rate_limit):
    response = client.post(
        "/v1/validate/report?format=pdf",
        json={"data": [{"velocity": 1.0}], "run_ai": False},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


def test_ros2_loader_preserves_effort_and_action_semantics(tmp_path, monkeypatch):
    bag_dir = tmp_path / "recording"
    bag_dir.mkdir()
    connection = SimpleNamespace(topic="/arm/joint_states", msgtype="sensor_msgs/msg/JointState")
    message = SimpleNamespace(
        name=["shoulder_pan_joint", "joint_2"],
        position=[0.1, 0.2], velocity=[0.3, 0.4], effort=[2.0, 3.0],
        header=SimpleNamespace(stamp=SimpleNamespace(sec=2, nanosec=500_000_000)),
    )

    reader_paths = []

    class FakeReader:
        connections = [connection]

        def __init__(self, paths):
            reader_paths.append(paths)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def messages(self, connections):
            yield connections[0], 2_500_000_000, b"message"

        def deserialize(self, _raw, _type):
            return message

    rosbags = types.ModuleType("rosbags")
    rosbags.__path__ = []
    highlevel = types.ModuleType("rosbags.highlevel")
    highlevel.AnyReader = FakeReader
    monkeypatch.setitem(sys.modules, "rosbags", rosbags)
    monkeypatch.setitem(sys.modules, "rosbags.highlevel", highlevel)

    frame = load_rosbag2(bag_dir)
    assert reader_paths[-1] == [bag_dir]
    assert frame.loc[0, "t"] == pytest.approx(2.5)
    assert frame.loc[0, "joint_shoulder_pan_joint_effort"] == 2.0
    assert frame.loc[0, "joint_2_effort"] == 3.0
    assert not any(column.startswith("action_") for column in frame.columns)

    standalone_db3 = tmp_path / "standalone.db3"
    standalone_db3.touch()
    load_rosbag2(standalone_db3)
    assert reader_paths[-1] == [standalone_db3]

    metadata_bag = tmp_path / "metadata_bag"
    metadata_bag.mkdir()
    (metadata_bag / "metadata.yaml").write_text("storage_identifier: sqlite3\n", encoding="utf-8")
    metadata_db3 = metadata_bag / "run_0.db3"
    metadata_db3.touch()
    load_rosbag2(metadata_db3)
    assert reader_paths[-1] == [metadata_bag]


def test_ros2_loader_rejects_malformed_joint_state_arrays(tmp_path, monkeypatch):
    bag_dir = tmp_path / "recording"
    bag_dir.mkdir()
    connection = SimpleNamespace(topic="/joint_states", msgtype="sensor_msgs/msg/JointState")
    message = SimpleNamespace(name=["joint_1", "joint_2"], position=[0.1], velocity=[], effort=[])

    class FakeReader:
        connections = [connection]

        def __init__(self, _paths):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def messages(self, connections):
            yield connections[0], 1_000_000_000, b"message"

        def deserialize(self, _raw, _type):
            return message

    rosbags = types.ModuleType("rosbags")
    rosbags.__path__ = []
    highlevel = types.ModuleType("rosbags.highlevel")
    highlevel.AnyReader = FakeReader
    monkeypatch.setitem(sys.modules, "rosbags", rosbags)
    monkeypatch.setitem(sys.modules, "rosbags.highlevel", highlevel)
    with pytest.raises(ValueError, match="position length"):
        load_rosbag2(bag_dir)


def test_lerobot_loader_rebases_chunk_episode_ids_and_uses_seconds(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "meta").mkdir()
    (dataset / "meta" / "info.json").write_text('{"fps": 2}', encoding="utf-8")
    first = dataset / "part-000.parquet"
    second = dataset / "part-001.parquet"
    first.touch()
    second.touch()
    frames = {
        first: pd.DataFrame({
            "episode_index": [0, 0, 0], "frame_index": [0, 1, 2],
            "observation.state": [[0.0], [0.5], [1.5]], "action": [[1.0], [2.0], [3.0]],
        }),
        second: pd.DataFrame({
            "episode_index": [0, 0], "frame_index": [0, 1],
            "observation.state": [[5.0], [5.5]], "action": [[4.0], [5.0]],
        }),
    }
    monkeypatch.setattr(pd, "read_parquet", lambda path: frames[Path(path)])

    result = load_lerobot(dataset)
    assert result["episode_id"].nunique() == 2
    assert result.attrs["time_unit"] == "seconds"
    assert result.loc[0, "joint_1_velocity"] == pytest.approx(1.0)
    assert result.loc[2, "joint_1_velocity"] == pytest.approx(2.0)
    assert result["action_1"].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_lerobot_loader_rejects_missing_episode_and_state_columns(tmp_path, monkeypatch):
    parquet = tmp_path / "part.parquet"
    parquet.touch()
    monkeypatch.setattr(pd, "read_parquet", lambda _path: pd.DataFrame({"frame_index": [0]}))
    with pytest.raises(ValueError, match="episode index"):
        load_lerobot(parquet)

    monkeypatch.setattr(pd, "read_parquet", lambda _path: pd.DataFrame({"episode_index": [0]}))
    with pytest.raises(ValueError, match="observation.state"):
        load_lerobot(parquet)
