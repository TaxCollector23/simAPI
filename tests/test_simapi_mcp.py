from __future__ import annotations

import base64
import io
import json
import zipfile

import pandas as pd
import pytest

pytest.importorskip("mcp")
pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient  # noqa: E402

import simapi_mcp as server  # noqa: E402


def _headers(token: str | None = None) -> dict[str, str]:
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        # The SDK's DNS rebinding check allows localhost by default.
        "host": "localhost:8000",
    }
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    return headers


def _event_json(response) -> dict:
    payload = next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
    return json.loads(payload)


def _start_session(client: TestClient, token: str) -> str:
    response = client.post(
        "/mcp",
        headers=_headers(token),
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "simapi-test", "version": "1.0"},
            },
        },
    )
    assert response.status_code == 200
    assert _event_json(response)["result"]["serverInfo"]["name"] == "simapi"
    return response.headers["mcp-session-id"]


def _call_tool(client: TestClient, token: str, session_id: str, name: str, arguments: dict, request_id: int = 2):
    headers = _headers(token)
    headers["mcp-session-id"] = session_id
    response = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200
    return _event_json(response)["result"]


def _tool_json(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def _parquet_bytes() -> bytes:
    pytest.importorskip("pyarrow")
    data = pd.DataFrame(
        {
            "episode_index": [0, 0, 0],
            "timestamp": [0.0, 0.02, 0.04],
            "observation.state": [[0.0, 0.2], [0.01, 0.21], [0.02, 0.22]],
        }
    )
    target = io.BytesIO()
    data.to_parquet(target, index=False)
    return target.getvalue()


def test_http_mode_requires_keys_at_startup(monkeypatch):
    monkeypatch.delenv("SIMAPI_MCP_API_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="SIMAPI_MCP_API_KEYS must contain"):
        server.build_http_app()


def test_http_authenticated_tools_and_recording_upload():
    app = server.build_http_app(api_keys=["good-token"])
    with TestClient(app) as client:
        missing = client.post("/mcp", headers=_headers(), json={})
        wrong = client.post("/mcp", headers=_headers("wrong-token"), json={})
        assert missing.status_code == 401
        assert missing.json() == {"error": "Unauthorized"}
        assert wrong.status_code == 401
        assert wrong.json() == {"error": "Unauthorized"}
        assert "good-token" not in missing.text + wrong.text

        session_id = _start_session(client, "good-token")

        headers = _headers("good-token")
        headers["mcp-session-id"] = session_id
        listed = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        names = {tool["name"] for tool in _event_json(listed)["result"]["tools"]}
        assert "validate_robotics_episode" in names
        assert "validate_recording_upload" in names

        report = _call_tool(
            client,
            "good-token",
            session_id,
            "validate_robotics_episode",
            {"rows": [
                {"time": 0.0, "joint_1_position": 0.1},
                {"time": 0.1, "joint_1_position": 0.2},
            ]},
            request_id=3,
        )
        assert report["isError"] is False
        tool_report = _tool_json(report)
        # Incomplete telemetry may legitimately produce a warning even when
        # the tool call succeeds. The MCP adapter must preserve that warning
        # instead of presenting it as a clean pass.
        assert tool_report["verdict"] in {"passed", "warning"}
        if tool_report["verdict"] == "warning":
            assert tool_report["warning_checks"]

        blocked = _call_tool(
            client,
            "good-token",
            session_id,
            "validate_recording",
            {"path": "/etc/passwd"},
            request_id=4,
        )
        assert blocked["isError"] is True
        assert "disabled in HTTP mode" in blocked["content"][0]["text"]

        uploaded = _call_tool(
            client,
            "good-token",
            session_id,
            "validate_recording_upload",
            {
                "content_base64": base64.b64encode(_parquet_bytes()).decode("ascii"),
                "filename": "tiny.parquet",
            },
            request_id=5,
        )
        assert uploaded["isError"] is False
        upload_report = _tool_json(uploaded)
        assert upload_report["format"] == "lerobot"
        assert upload_report["rows"] == 3
        assert upload_report["source"] == "tiny.parquet"


def test_http_rate_limit_returns_429_and_retry_after():
    async def ok_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = server.MCPHTTPAuthRateLimit(ok_app, ["rate-token", "other-token"], 2)
    client = TestClient(app)
    first = client.get("/mcp", headers=_headers("rate-token"))
    second = client.get("/mcp", headers=_headers("rate-token"))
    third = client.get("/mcp", headers=_headers("rate-token"))
    other_token = client.get("/mcp", headers=_headers("other-token"))

    assert first.status_code != 429
    assert second.status_code != 429
    assert third.status_code == 429
    assert int(third.headers["retry-after"]) >= 1
    assert third.json() == {"error": "Rate limit exceeded"}
    assert other_token.status_code != 429


def test_row_cap_applies_to_episode_csv_and_export_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_HTTP_MODE", False)
    monkeypatch.setenv("SIMAPI_MCP_TRANSPORT", "stdio")
    monkeypatch.setenv("SIMAPI_MCP_MAX_ROWS", "3")
    rows = [{"joint_1_position": float(index)} for index in range(4)]

    with pytest.raises(ValueError, match=r"4 rows; SIMAPI_MCP_MAX_ROWS is 3"):
        server.validate_robotics_episode(rows)
    with pytest.raises(ValueError, match=r"4 rows; SIMAPI_MCP_MAX_ROWS is 3"):
        server.export_clean_episodes(rows)

    csv_path = tmp_path / "too-many.csv"
    csv_path.write_text("joint_1_position\n0\n1\n2\n3\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"at least 4 rows; SIMAPI_MCP_MAX_ROWS is 3"):
        server.validate_robotics_csv(str(csv_path))


def test_http_mode_refuses_local_csv_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_HTTP_MODE", True)
    csv_path = tmp_path / "private.csv"
    csv_path.write_text("joint_1_position\n50000\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Local CSV paths are disabled in HTTP mode"):
        server.validate_robotics_csv(str(csv_path))


@pytest.mark.parametrize(
    "limits",
    [
        {"joint_1_torque": [True, 1.0]},
        {"joint_1_torque": [float("nan"), 1.0]},
        {"joint_1_torque": [0.0, float("inf")]},
        {"joint_1_torque": [1.0, 1.0]},
    ],
)
def test_explicit_limits_reject_boolean_nonfinite_or_equal_bounds(limits):
    with pytest.raises(ValueError, match="joint_1_torque"):
        server._validate_limits(limits)


def test_warning_checks_are_not_clean_passes_or_exported(monkeypatch):
    warning = {
        "name": "robotics_time_coverage",
        "status": "warning",
        "detail": "No usable time column.",
    }

    def warning_report(*args, **kwargs):
        return {
            "checks": [warning],
            "excluded": {},
            "summary": {"episodes": []},
            "evidence": {},
        }

    monkeypatch.setattr(server, "check_robotics_limits", warning_report)
    rows = [{"episode_id": "missing-time", "joint_1_position": 0.1}]

    report = server.validate_robotics_episode(rows)
    exported = server.export_clean_episodes(rows)

    assert report["verdict"] == "warning"
    assert report["warning_checks"] == [{
        "name": "robotics_time_coverage", "detail": "No usable time column."
    }]
    assert exported["clean_rows"] == []
    assert exported["kept_episodes"] == []
    assert exported["removed_episodes"][0]["warning_checks"] == report["warning_checks"]


def test_recording_row_cap_is_passed_to_loaders_before_conversion(monkeypatch, tmp_path):
    from integrations import lerobot_loader, robotics_validation, ros2_loader

    monkeypatch.setenv("SIMAPI_MCP_MAX_ROWS", "7")
    frame = pd.DataFrame({
        "episode_id": ["one"],
        "t": [0.0],
        "joint_1_position": [0.1],
    })
    calls = []

    def load_lerobot(path, *, max_episodes=None, max_rows=None):
        calls.append(("lerobot", max_rows))
        return frame

    def load_rosbag2(path, *, topic_hint="joint_states", max_rows=None):
        calls.append(("rosbag", max_rows))
        return frame

    def validate_frame(data, *, limits=None, conditions=None, time_unit="seconds"):
        return {
            "checks": [{"name": "ok", "status": "passed", "detail": "ok"}],
            "status": "passed",
            "exclusions": {},
            "episodes": [],
            "rows": len(data),
        }

    monkeypatch.setattr(lerobot_loader, "load_lerobot", load_lerobot)
    monkeypatch.setattr(ros2_loader, "load_rosbag2", load_rosbag2)
    monkeypatch.setattr(robotics_validation, "validate_robotics_frame", validate_frame)

    parquet = tmp_path / "data.parquet"
    parquet.write_bytes(b"fixture")
    bag = tmp_path / "bag"
    bag.mkdir()
    server._validate_recording_path(parquet, None, None, None, "joint_states", None)
    server._validate_recording_path(bag, None, None, None, "joint_states", None)

    assert calls == [("lerobot", 7), ("rosbag", 7)]


def test_zip_entry_count_is_bounded_before_extraction(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMAPI_MCP_MAX_ZIP_ENTRIES", "1")
    archive_path = tmp_path / "many-empty.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("first.txt", b"")
        archive.writestr("second.txt", b"")
    destination = tmp_path / "extracted"

    with pytest.raises(ValueError, match="SIMAPI_MCP_MAX_ZIP_ENTRIES is 1"):
        server._safe_extract_zip(archive_path, destination)

    assert not destination.exists()


def test_upload_rejects_invalid_base64_and_unsupported_content():
    with pytest.raises(ValueError, match="valid base64"):
        server.validate_recording_upload("not-base64!", "run.parquet")
    with pytest.raises(ValueError, match="Unsupported recording content"):
        server.validate_recording_upload(
            base64.b64encode(b"plain text").decode("ascii"), "run.csv"
        )


def test_stdio_recording_path_remains_available(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "_HTTP_MODE", False)
    monkeypatch.setenv("SIMAPI_MCP_TRANSPORT", "stdio")
    upload_path = tmp_path / "local.parquet"
    upload_path.write_bytes(_parquet_bytes())

    report = server.validate_recording(str(upload_path))

    assert report["format"] == "lerobot"
    assert report["rows"] == 3
