"""Hosted ingestion tests for physical robotics recordings."""

from __future__ import annotations

import io
import zipfile
from dataclasses import replace

import pandas as pd
import pytest

from api import server
from core.physics_validator import SimulationType


@pytest.fixture()
def recording_client(client):
    previous = server.app.dependency_overrides.get(server.caller_identity)
    server.app.dependency_overrides[server.caller_identity] = lambda: "recording-upload-test"
    try:
        yield client
    finally:
        if previous is None:
            server.app.dependency_overrides.pop(server.caller_identity, None)
        else:
            server.app.dependency_overrides[server.caller_identity] = previous


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return payload.getvalue()


def _frame(rows: int = 2) -> pd.DataFrame:
    return pd.DataFrame([
        {"episode_id": "episode-1", "t": index * 0.1, "joint_1_position": index * 0.01}
        for index in range(rows)
    ])


@pytest.mark.parametrize(
    ("filename", "payload", "expected_format", "expected_suffix"),
    [
        ("bag.anything", b"SQLite format 3\x00" + b"x" * 20, "rosbag2", ".db3"),
        ("capture.bin", b"\x89MCAP0\r\n" + b"x" * 20, "mcap", ".mcap"),
        ("shard.data", b"PAR1" + b"x" * 20, "lerobot", ".parquet"),
        (
            "bag.zip",
            _zip_bytes({
                "ros2_run/metadata.yaml": b"rosbag2_bagfile_information:\n",
                "ros2_run/run_0.db3": b"SQLite format 3\x00" + b"x" * 20,
            }),
            "rosbag2",
            "",
        ),
        (
            "dataset.zip",
            _zip_bytes({"data/chunk-0.parquet": b"PAR1" + b"x" * 20}),
            "lerobot",
            "",
        ),
        (
            "capture.zip",
            _zip_bytes({"recording.mcap": b"\x89MCAP0\r\n" + b"x" * 20}),
            "mcap",
            ".mcap",
        ),
    ],
)
def test_recording_route_detects_content_and_reuses_loaders(
    recording_client, monkeypatch, filename, payload, expected_format, expected_suffix
):
    seen: dict[str, object] = {}

    def fake_rosbag(path, *, topic_hint):
        seen["loader"] = "rosbag2"
        seen["path"] = path
        seen["topic_hint"] = topic_hint
        return _frame()

    def fake_lerobot(path):
        seen["loader"] = "lerobot"
        seen["path"] = path
        return _frame()

    async def fake_validate(req):
        seen["request"] = req
        return {"status": "pass", "issues": []}

    monkeypatch.setattr("integrations.ros2_loader.load_rosbag2", fake_rosbag)
    monkeypatch.setattr("integrations.lerobot_loader.load_lerobot", fake_lerobot)
    monkeypatch.setattr(server, "_validate_core", fake_validate)

    response = recording_client.post(
        "/v1/validate/recording",
        files={"file": (filename, payload, "application/octet-stream")},
        data={
            "topic_hint": "/arm/joint_states",
            "robotics_limits": '{"joint_1_position":[-1.0,1.0]}',
            "conditions": '{"max_time_step":0.2}',
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "pass"
    assert result["recording"]["format"] == expected_format
    assert result["recording"]["rows"] == 2
    assert result["recording"]["source_name"] == filename
    assert seen["loader"] == ("lerobot" if expected_format == "lerobot" else "rosbag2")
    if expected_suffix:
        assert str(seen["path"]).endswith(expected_suffix)
    if expected_format in {"rosbag2", "mcap"}:
        assert seen["topic_hint"] == "/arm/joint_states"
    request = seen["request"]
    assert request.simulation_type is SimulationType.ROBOTICS
    assert request.robotics_limits == {"joint_1_position": (-1.0, 1.0)}
    assert request.conditions == {"max_time_step": 0.2}
    assert request.run_ai is False
    assert len(request.data) == 2


def test_recording_returns_the_standard_robotics_validation_report(recording_client, monkeypatch):
    def fake_lerobot(_path):
        return _frame(24)

    monkeypatch.setattr("integrations.lerobot_loader.load_lerobot", fake_lerobot)
    response = recording_client.post(
        "/v1/validate/recording",
        files={"file": ("episode.parquet", b"PAR1" + b"x" * 20, "application/octet-stream")},
        data={"robotics_limits": '{"joint_1_position":[-1.0,1.0]}'},
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert {"status", "training_ready", "issues", "robotics_summary"} <= report.keys()
    assert report["recording"] == {
        "format": "lerobot",
        "rows": 24,
        "source_name": "episode.parquet",
    }


def test_recording_rejects_unsupported_content(recording_client):
    response = recording_client.post(
        "/v1/validate/recording", files={"file": ("recording.db3", b"plain text", "application/octet-stream")}
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_format"


def test_recording_requires_json_objects_in_form_fields(recording_client):
    response = recording_client.post(
        "/v1/validate/recording",
        files={"file": ("recording.db3", b"SQLite format 3\x00", "application/octet-stream")},
        data={"robotics_limits": "[]"},
    )
    assert response.status_code == 400
    assert "robotics_limits" in response.json()["error"]["message"]


@pytest.mark.parametrize("entry_name", ["../outside.db3", "..\\\\outside.db3"])
def test_recording_rejects_zip_path_traversal(recording_client, entry_name):
    response = recording_client.post(
        "/v1/validate/recording",
        files={
            "file": (
                "recording.zip",
                _zip_bytes({entry_name: b"SQLite format 3\x00"}),
                "application/zip",
            )
        },
    )
    assert response.status_code == 400
    assert "escapes" in response.json()["error"]["message"]


def test_recording_upload_limit_is_enforced_while_streaming(recording_client, monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, max_upload_bytes=8))
    response = recording_client.post(
        "/v1/validate/recording",
        files={"file": ("recording.mcap", b"\x89MCAP0\r\n" + b"oversize", "application/octet-stream")},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_recording_zip_expansion_limit_is_enforced(recording_client, monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, max_upload_bytes=512))
    payload = _zip_bytes({"episode.parquet": b"PAR1" + b"x" * 5000})
    assert len(payload) < 512
    response = recording_client.post(
        "/v1/validate/recording",
        files={"file": ("episode.zip", payload, "application/zip")},
    )
    assert response.status_code == 413
    assert "Expanded recording ZIP" in response.json()["error"]["message"]


def test_recording_refuses_more_than_configured_sample_limit(recording_client, monkeypatch):
    monkeypatch.setattr(server, "settings", replace(server.settings, max_recording_rows=2))
    monkeypatch.setattr("integrations.lerobot_loader.load_lerobot", lambda _path: _frame(3))

    async def should_not_validate(_req):
        pytest.fail("validation must not run after the converted-row cap is exceeded")

    monkeypatch.setattr(server, "_validate_core", should_not_validate)
    response = recording_client.post(
        "/v1/validate/recording",
        files={"file": ("part.parquet", b"PAR1" + b"x" * 20, "application/octet-stream")},
    )
    assert response.status_code == 413
    assert response.json()["error"]["details"] == {"rows": 3, "limit": 2}


def test_recording_reports_missing_optional_reader_as_server_capability(recording_client, monkeypatch):
    def missing_reader(_path):
        raise RuntimeError("LeRobot dataset support requires the optional 'pyarrow' package")

    monkeypatch.setattr("integrations.lerobot_loader.load_lerobot", missing_reader)
    response = recording_client.post(
        "/v1/validate/recording",
        files={"file": ("part.parquet", b"PAR1" + b"x" * 20, "application/octet-stream")},
    )
    assert response.status_code == 501
    assert "robotics-data" in response.json()["error"]["message"]
