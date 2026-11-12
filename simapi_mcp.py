"""
SimAPI MCP server (prototype).

Lets Claude / ChatGPT-style MCP clients call SimAPI's robotics validator
as a tool, in plain conversation:

    User:    "Check this robot run, is any of it lying?"
    AI:      *calls validate_robotics_episode*
    SimAPI:  {verdict: "failed", excluded rows + exact reasons}
    AI:      "Row at t=0.08s is bad: the joint teleported..."

Run it from inside the SimAPI repo, or set SIMAPI_PATH to the repo root:

    SIMAPI_PATH=/path/to/simapi python simapi_mcp.py            # stdio (Claude Desktop / Claude Code)
    SIMAPI_MCP_TRANSPORT=streamable-http python simapi_mcp.py   # HTTP (remote clients, e.g. ChatGPT)

Requires:  pip install "mcp<2" pandas
"""
import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import sqlite3
import sys
import tempfile
import threading
import time
import zipfile
from collections.abc import Mapping
from pathlib import Path

# --- find the SimAPI repo so we can import its real engine, not a copy ---
REPO = os.environ.get("SIMAPI_PATH") or str(Path(__file__).resolve().parent)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import pandas as pd  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

from core.robotics_engine import DEFAULT_ROBOTICS_LIMITS  # noqa: E402
from core.robotics_validation import check_robotics_limits  # noqa: E402

mcp = FastMCP("simapi")

_HTTP_MODE = os.environ.get("SIMAPI_MCP_TRANSPORT", "stdio").lower() == "streamable-http"
_DEFAULT_MAX_ROWS = 10_000
_DEFAULT_MAX_ZIP_ENTRIES = 10_000
# Keep base64 uploads within the MCP SDK's default 4 MiB HTTP body ceiling.
_MAX_UPLOAD_BYTES = 3 * 1024 * 1024

CHECK_GLOSSARY = {
    "robotics_limit": "A value went outside the allowed range for that signal "
                      "(e.g. torque 95 when the max is 70).",
    "robotics_derived_limit": "The motion implied by the data broke a limit. "
                              "Example: positions imply the joint moved at 57 rad/s "
                              "even though the velocity limit is 2 rad/s.",
    "robotics_consistency": "Two signals disagree with each other. Example: position "
                            "changes imply velocity 57, but the recorded velocity says 1.0. "
                            "At least one of them is lying.",
    "robotics_time_order": "Time went backwards or repeated inside an episode.",
    "robotics_sample_gaps": "There is a silent gap in time bigger than max_time_step "
                            "(missing samples).",
    "robotics_time_coverage": "No usable time column, so motion checks could not run.",
}


def _clean_report(report: dict) -> dict:
    """Turn the engine's report into a small JSON-friendly verdict for an AI to explain."""
    checks = report.get("checks", [])
    failed = [c for c in checks if c.get("status") == "failed"]
    warnings = [c for c in checks if c.get("status") == "warning"]
    excluded = {
        str(row): reasons for row, reasons in (report.get("excluded") or {}).items()
    }
    return {
        "verdict": "failed" if failed else "warning" if warnings else "passed",
        "failed_checks": [
            {"name": c["name"], "detail": c.get("detail", "")} for c in failed
        ],
        "warning_checks": [
            {"name": c["name"], "detail": c.get("detail", "")} for c in warnings
        ],
        "all_checks": [
            {"name": c["name"], "status": c.get("status"), "detail": c.get("detail", "")}
            for c in checks
        ],
        "excluded_rows": excluded,
        "episodes": (report.get("summary") or {}).get("episodes", []),
    }


def _validate_limits(robotics_limits: dict | None) -> dict:
    """Validate finite, non-degenerate bounds before they reach the engine."""
    if robotics_limits is not None and not isinstance(robotics_limits, Mapping):
        raise ValueError("robotics_limits must map signal names to [min, max] pairs")
    limits: dict = {}
    for name, rng in (robotics_limits or {}).items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("robotics_limits signal names must be non-empty strings")
        if isinstance(rng, (str, bytes)):
            raise ValueError(
                f"robotics_limits[{name!r}] must be a [min, max] pair of finite numbers"
            )
        try:
            lo, hi = rng
            if isinstance(lo, bool) or isinstance(hi, bool):
                raise ValueError
            pair = (float(lo), float(hi))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"robotics_limits[{name!r}] must be a [min, max] pair of "
                f"finite numbers, got {rng!r}"
            ) from exc
        if not all(math.isfinite(value) for value in pair):
            raise ValueError(f"robotics_limits[{name!r}] bounds must be finite, got {rng!r}")
        if pair[0] >= pair[1]:
            raise ValueError(
                f"robotics_limits[{name!r}] minimum must be less than maximum: {rng!r}"
            )
        limits[name] = pair
    return limits


def _run(rows: list[dict], robotics_limits: dict | None,
         max_time_step: float | None, velocity_tolerance: float | None) -> dict:
    _enforce_row_cap(len(rows))
    if not rows:
        # Fail closed: nothing to validate is not a pass.
        return {
            "verdict": "failed",
            "failed_checks": [{"name": "no_data",
                               "detail": "No rows provided — nothing to validate."}],
            "all_checks": [],
            "excluded_rows": {},
            "episodes": [],
        }
    conditions: dict = {}
    if max_time_step is not None:
        conditions["max_time_step"] = max_time_step
    if velocity_tolerance is not None:
        conditions["velocity_tolerance"] = velocity_tolerance
    limits = _validate_limits(robotics_limits)
    report = check_robotics_limits(
        pd.DataFrame(rows), limits, source_rows=rows, conditions=conditions
    )
    return _clean_report(report)


def _positive_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _max_rows() -> int:
    return _positive_env_int("SIMAPI_MCP_MAX_ROWS", _DEFAULT_MAX_ROWS)


def _max_zip_entries() -> int:
    return _positive_env_int("SIMAPI_MCP_MAX_ZIP_ENTRIES", _DEFAULT_MAX_ZIP_ENTRIES)


def _enforce_row_cap(count: int, *, lower_bound: bool = False) -> None:
    cap = _max_rows()
    if count > cap:
        observed = f"at least {count}" if lower_bound else str(count)
        raise ValueError(f"Recording has {observed} rows; SIMAPI_MCP_MAX_ROWS is {cap}.")


@mcp.tool()
def validate_robotics_episode(
    rows: list[dict],
    robotics_limits: dict | None = None,
    max_time_step: float | None = None,
    velocity_tolerance: float | None = None,
) -> dict:
    """Validate robot-arm trajectory data with SimAPI.

    rows: list of samples, one dict per moment in time, e.g.
          {"episode_id": "pick_cup_01", "time": 0.02,
           "joint_1_position": 0.02, "joint_1_velocity": 1.0, "joint_1_torque": 6.0}
          Positions in radians, time in seconds. Multiple episodes per call are OK
          if each row has an episode_id.
    robotics_limits: allowed [min, max] per signal, e.g.
          {"joint_1_position": [-1.57, 1.57], "joint_1_torque": [-70, 70]}.
          Signals not listed fall back to very wide screening defaults.
    max_time_step: optional, seconds. Flag silent time gaps bigger than this.
    velocity_tolerance: optional, absolute. Also check that velocity implied by
          position changes agrees with the recorded velocity.
    Returns verdict (passed/failed), the checks that failed, and the exact
    excluded rows with reasons.
    """
    return _run(rows, robotics_limits, max_time_step, velocity_tolerance)


@mcp.tool()
def validate_robotics_csv(
    csv_path: str,
    robotics_limits: dict | None = None,
    max_time_step: float | None = None,
    velocity_tolerance: float | None = None,
) -> dict:
    """Validate a CSV file of robot trajectory data with SimAPI.

    The CSV needs one row per sample and columns like time, episode_id,
    joint_1_position, joint_1_velocity, joint_1_torque.
    Same limits/conditions as validate_robotics_episode. Local paths are
    available in stdio mode only; HTTP clients must send rows or use uploads.
    """
    if _HTTP_MODE or os.environ.get("SIMAPI_MCP_TRANSPORT", "stdio").lower() == "streamable-http":
        raise ValueError(
            "Local CSV paths are disabled in HTTP mode. Send rows to "
            "validate_robotics_episode or upload a supported recording instead."
        )
    df = pd.read_csv(csv_path, nrows=_max_rows() + 1)
    rows = df.where(pd.notnull(df), None).to_dict("records")
    _enforce_row_cap(len(rows), lower_bound=True)
    return _run(rows, robotics_limits, max_time_step, velocity_tolerance)


def _clean_loader_report(report: dict) -> dict:
    """Adapt a loader report (validate_rosbag2 / validate_lerobot) to the
    same verdict shape as _clean_report. Loader reports use 'status' and
    'exclusions' (int keys) instead of 'verdict'/'excluded'."""
    checks = report.get("checks", [])
    failed = [c for c in checks if c.get("status") == "failed"]
    warnings = [c for c in checks if c.get("status") == "warning"]
    status = report.get("status")
    if status == "failed" or failed:
        verdict = "failed"
    elif status == "warning" or warnings:
        verdict = "warning"
    else:
        verdict = status or "passed"
    excluded = {
        str(row): reasons for row, reasons in (report.get("exclusions") or {}).items()
    }
    out = {
        "verdict": verdict,
        "failed_checks": [
            {"name": c["name"], "detail": c.get("detail", "")} for c in failed
        ],
        "warning_checks": [
            {"name": c["name"], "detail": c.get("detail", "")} for c in warnings
        ],
        "all_checks": [
            {"name": c["name"], "status": c.get("status"), "detail": c.get("detail", "")}
            for c in checks
        ],
        "excluded_rows": excluded,
        "episodes": report.get("episodes", []),
        "rows": report.get("rows"),
        "source": report.get("source"),
        "format": report.get("format"),
    }
    if "n_episodes" in report:
        out["n_episodes"] = report["n_episodes"]
    return out


def _validate_recording_path(
    path: str | Path,
    robotics_limits: dict | None,
    max_time_step: float | None,
    velocity_tolerance: float | None,
    topic_hint: str,
    max_episodes: int | None,
) -> dict:
    """Load a recording once, enforce the configured row cap, then validate it."""
    from integrations.lerobot_loader import load_lerobot
    from integrations.robotics_validation import validate_robotics_frame
    from integrations.ros2_loader import load_rosbag2

    limits, conditions = _limits_and_conditions(
        robotics_limits, max_time_step, velocity_tolerance
    )
    target = Path(path).expanduser()
    if not target.exists():
        raise FileNotFoundError(f"No recording found at {path}")
    is_lerobot = (
        target.suffix.lower() == ".parquet"
        or (target.is_dir() and any(target.rglob("*.parquet")))
    )
    max_rows = _max_rows()
    if is_lerobot:
        frame = load_lerobot(target, max_episodes=max_episodes, max_rows=max_rows)
        recording_format = "lerobot"
        time_unit = str(frame.attrs.get("time_unit", "seconds"))
    else:
        frame = load_rosbag2(target, topic_hint=topic_hint, max_rows=max_rows)
        recording_format = "rosbag2"
        time_unit = "seconds"
    _enforce_row_cap(len(frame))
    report = validate_robotics_frame(
        frame,
        limits=limits or None,
        conditions=conditions or None,
        time_unit=time_unit,
    )
    report["source"] = str(path)
    report["format"] = recording_format
    if recording_format == "lerobot":
        report["n_episodes"] = int(frame["episode_id"].nunique())
    return _clean_loader_report(report)


def _limits_and_conditions(robotics_limits, max_time_step, velocity_tolerance):
    conditions: dict = {}
    if max_time_step is not None:
        conditions["max_time_step"] = max_time_step
    if velocity_tolerance is not None:
        conditions["velocity_tolerance"] = velocity_tolerance
    return _validate_limits(robotics_limits), conditions


@mcp.tool()
def validate_recording(
    path: str,
    robotics_limits: dict | None = None,
    max_time_step: float | None = None,
    velocity_tolerance: float | None = None,
    topic_hint: str = "joint_states",
    max_episodes: int | None = None,
) -> dict:
    """Validate a robot recording file straight from chat — no CSV conversion.

    path: a LeRobot dataset (a folder of .parquet shards, or one .parquet file),
          or a ROS 2 recording (a rosbag2 folder, a .db3 file, or a .mcap file).
          The format is picked from the path: parquet present -> LeRobot,
          anything else -> ROS bag reader.
    robotics_limits: allowed [min, max] per signal, e.g.
          {"joint_1_position": [-1.57, 1.57], "joint_1_velocity": [-2, 2]}.
          NOTE for ROS bags: effort comes through as joint_N_effort, not
          joint_N_torque — put torque limits under the _effort name.
    max_time_step / velocity_tolerance: same as validate_robotics_episode.
    topic_hint: ROS topic substring to read JointState messages from
          (default "joint_states").
    max_episodes: LeRobot only — validate at most this many episodes.
    Returns the same verdict shape as validate_robotics_episode, plus
    source, format, rows and n_episodes (LeRobot).
    Needs the optional deps: pip install rosbags pyarrow
    (SimAPI's robotics-data extra). LeRobot data usually has positions only;
    velocities are derived from position changes, so the lie-detector checks
    still run.
    """
    if _HTTP_MODE or os.environ.get("SIMAPI_MCP_TRANSPORT", "stdio").lower() == "streamable-http":
        raise ValueError(
            "Local recording paths are disabled in HTTP mode. Use validate_recording_upload instead."
        )
    return _validate_recording_path(
        path,
        robotics_limits,
        max_time_step,
        velocity_tolerance,
        topic_hint,
        max_episodes,
    )


def _safe_extract_zip(archive_path: Path, destination: Path) -> Path:
    """Extract a bounded recording archive without allowing path traversal."""
    total_size = 0
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        max_entries = _max_zip_entries()
        if len(members) > max_entries:
            raise ValueError(
                f"Recording zip has {len(members)} entries; "
                f"SIMAPI_MCP_MAX_ZIP_ENTRIES is {max_entries}."
            )
        for member in members:
            path = Path(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Recording zip contains an unsafe path.")
            if member.is_dir():
                continue
            total_size += member.file_size
            if total_size > _MAX_UPLOAD_BYTES:
                raise ValueError("Recording zip expands beyond the 3 MiB upload limit.")
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as sink:
                copied = 0
                while chunk := source.read(1024 * 1024):
                    copied += len(chunk)
                    if copied > member.file_size or copied > _MAX_UPLOAD_BYTES:
                        raise ValueError("Recording zip entry exceeded its declared size.")
                    sink.write(chunk)
    parquet = next(destination.rglob("*.parquet"), None)
    if parquet is not None:
        return destination
    metadata = next(destination.rglob("metadata.yaml"), None)
    db3 = next(destination.rglob("*.db3"), None)
    mcap = next(destination.rglob("*.mcap"), None)
    if metadata is not None and (db3 is not None or mcap is not None):
        return metadata.parent
    if mcap is not None:
        return mcap
    if db3 is not None:
        if metadata is None:
            _write_rosbag2_metadata(db3)
        return db3.parent
    raise ValueError("Zip must contain a LeRobot parquet dataset or a rosbag2 bag.")


def _write_rosbag2_metadata(database: Path) -> None:
    """Create rosbag2 metadata for a standalone SQLite bag upload."""
    try:
        database_uri = f"{database.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(database_uri, uri=True) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(topics)")}
            if not {"id", "name", "type"}.issubset(columns):
                raise ValueError("The SQLite file is not a rosbag2 database.")
            qos_expr = "offered_qos_profiles" if "offered_qos_profiles" in columns else "'[]'"
            topic_rows = connection.execute(
                f"SELECT id, name, type, serialization_format, {qos_expr} FROM topics"
            ).fetchall()
            if not topic_rows:
                raise ValueError("The rosbag2 database contains no topics.")
            lower, upper, message_count = connection.execute(
                "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM messages"
            ).fetchone()
            topic_summaries = []
            for topic_id, name, msgtype, serialization, qos in topic_rows:
                (topic_count,) = connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE topic_id = ?", (topic_id,)
                ).fetchone()
                topic_summaries.append({
                    "topic_metadata": {
                        "name": name,
                        "type": msgtype,
                        "serialization_format": serialization or "cdr",
                        "offered_qos_profiles": qos or "[]",
                    },
                    "message_count": topic_count,
                })
    except sqlite3.Error as exc:
        raise ValueError("The SQLite upload is not a readable rosbag2 database.") from exc

    metadata = {
        "rosbag2_bagfile_information": {
            "version": 5,
            "storage_identifier": "sqlite3",
            "relative_file_paths": [database.name],
            "duration": {"nanoseconds": max(0, int(upper or 0) - int(lower or 0))},
            "starting_time": {"nanoseconds_since_epoch": int(lower or 0)},
            "message_count": int(message_count or 0),
            "compression_format": "",
            "compression_mode": "",
            "topics_with_message_count": topic_summaries,
            "files": [],
            "custom_data": None,
            "ros_distro": "unknown",
        }
    }
    # JSON is valid YAML, so the wrapper does not add a YAML dependency.
    database.parent.joinpath("metadata.yaml").write_text(json.dumps(metadata), encoding="utf-8")


@mcp.tool()
def validate_recording_upload(
    content_base64: str,
    filename: str,
    robotics_limits: dict | None = None,
    max_time_step: float | None = None,
    velocity_tolerance: float | None = None,
    topic_hint: str = "joint_states",
    max_episodes: int | None = None,
) -> dict:
    """Validate an uploaded recording in HTTP mode.

    content_base64: base64-encoded bytes from one .parquet, .db3, .mcap or .zip file.
    filename: original file name; only its final path component is used.
    """
    if not isinstance(content_base64, str) or not isinstance(filename, str):
        raise ValueError("content_base64 and filename are required strings.")
    approximate_bytes = (len(content_base64) * 3) // 4
    if approximate_bytes > _MAX_UPLOAD_BYTES + 2:
        raise ValueError("Recording upload exceeds the 3 MiB limit.")
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("content_base64 must be valid base64.") from exc
    if len(content) > _MAX_UPLOAD_BYTES:
        raise ValueError("Recording upload exceeds the 3 MiB limit.")

    clean_name = Path(filename).name
    if not clean_name or clean_name in {".", ".."}:
        raise ValueError("filename must include a supported recording extension.")
    with tempfile.TemporaryDirectory(prefix="simapi-mcp-") as temp_name:
        temp_dir = Path(temp_name)
        upload = temp_dir / clean_name
        upload.write_bytes(content)
        if content.startswith(b"PAR1") and clean_name.lower().endswith(".parquet"):
            recording_path = upload
        elif content.startswith(b"SQLite format 3\x00") and clean_name.lower().endswith(".db3"):
            recording_dir = temp_dir / "rosbag"
            recording_dir.mkdir()
            staged_db = recording_dir / clean_name
            upload.replace(staged_db)
            _write_rosbag2_metadata(staged_db)
            recording_path = staged_db
        elif content.startswith(b"\x89MCAP0\r\n") and clean_name.lower().endswith(".mcap"):
            recording_path = upload
        elif content.startswith(b"PK\x03\x04") and clean_name.lower().endswith(".zip"):
            recording_path = _safe_extract_zip(upload, temp_dir / "extracted")
        else:
            raise ValueError(
                "Unsupported recording content. Upload a LeRobot .parquet, rosbag2 .db3/.mcap, or .zip."
            )
        report = _validate_recording_path(
            recording_path,
            robotics_limits,
            max_time_step,
            velocity_tolerance,
            topic_hint,
            max_episodes,
        )
        report["source"] = clean_name
        return report


_EPISODE_KEYS = ("episode_id", "episode", "trajectory_id", "sequence_id")


@mcp.tool()
def export_clean_episodes(
    rows: list[dict],
    robotics_limits: dict | None = None,
    max_time_step: float | None = None,
    velocity_tolerance: float | None = None,
) -> dict:
    """Export ONLY the clean episodes from robot trajectory data.

    Each episode (grouped by episode_id) is validated on its own with
    SimAPI. Episodes with no failed or warning checks are kept whole — every
    row in the original order. Episodes with a failed or warning check are removed
    whole (cutting single rows out would leave silent time gaps inside
    a movement, which is its own kind of bad training data). Warnings are
    not training-ready and appear under warning_checks in removed_episodes.

    rows / robotics_limits / max_time_step / velocity_tolerance: same as
    validate_robotics_episode.

    Returns:
      clean_rows:       the rows to train on (clean episodes only).
      kept_episodes:    episode ids that passed.
      removed_episodes: [{episode_id, rows_removed, failed_checks,
                          warning_checks}] —
                        what was taken out and WHY, never silently.
      summary:          row/episode counts in and out.
    """
    _enforce_row_cap(len(rows))
    key = next((k for k in _EPISODE_KEYS if any(k in r for r in rows)), None)
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in rows:
        name = str(row.get(key, "(missing episode)")) if key else "Episode 1"
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append(row)

    kept: list[str] = []
    removed: list[dict] = []
    for name in order:
        ep_rows = groups[name]
        result = _run(ep_rows, robotics_limits, max_time_step, velocity_tolerance)
        if result["verdict"] == "passed":
            kept.append(name)
        else:
            removed.append({
                "episode_id": name,
                "rows_removed": len(ep_rows),
                "failed_checks": result["failed_checks"],
                "warning_checks": result["warning_checks"],
                "excluded_rows_within_episode": result["excluded_rows"],
            })
    # Preserve the caller's original row order exactly (episodes are
    # normally contiguous, but interleaved input must not be re-sorted).
    kept_set = set(kept)
    clean_rows = [
        row for row in rows
        if (str(row.get(key, "(missing episode)")) if key else "Episode 1") in kept_set
    ]
    return {
        "clean_rows": clean_rows,
        "kept_episodes": kept,
        "removed_episodes": removed,
        "summary": {
            "rows_in": len(rows),
            "rows_out": len(clean_rows),
            "episodes_in": len(order),
            "episodes_kept": len(kept),
            "episodes_removed": len(removed),
        },
    }


@mcp.tool()
def get_default_robotics_limits() -> dict:
    """The built-in (very wide, screening-only) SimAPI robotics limits per signal
    type. Real value comes from passing a robot's own limits to the validate tools."""
    return {name: list(rng) for name, rng in DEFAULT_ROBOTICS_LIMITS.items()}


@mcp.tool()
def explain_robotics_check(check_name: str) -> str:
    """Plain-English explanation of a SimAPI robotics check name, e.g.
    'robotics_derived_limit:joint_1_velocity' or 'robotics_time_order'."""
    base = check_name.split(":", 1)[0]
    return CHECK_GLOSSARY.get(
        base, f"No glossary entry for {check_name!r} yet."
    )


class MCPHTTPAuthRateLimit:
    """ASGI guard for hosted MCP requests.

    The SDK exposes a Starlette app for Streamable HTTP, so this wrapper can
    reject unauthenticated traffic before any MCP message reaches a tool.
    Rate counters intentionally live in memory; deployment is single-process.
    """

    def __init__(self, app, api_keys: list[str], requests_per_minute: int):
        self.app = app
        self.api_keys = tuple(key.encode("utf-8") for key in api_keys)
        self.requests_per_minute = requests_per_minute
        self._lock = threading.Lock()
        self._windows: dict[bytes, tuple[int, int]] = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        authorization = [
            value for name, value in scope.get("headers", [])
            if name.lower() == b"authorization"
        ]
        token = self._authorized_token(authorization)
        if token is None:
            await self._respond(send, 401, {"error": "Unauthorized"})
            return

        now = time.monotonic()
        window = int(now // 60)
        digest = hashlib.sha256(token).digest()
        with self._lock:
            prior_window, count = self._windows.get(digest, (window, 0))
            if prior_window != window:
                count = 0
            if count >= self.requests_per_minute:
                retry_after = max(1, math.ceil(60 - (now % 60)))
                throttled = True
            else:
                self._windows[digest] = (window, count + 1)
                throttled = False
                retry_after = 0
            if len(self._windows) > 2048:
                self._windows = {
                    key: value for key, value in self._windows.items()
                    if value[0] >= window - 1
                }
        if throttled:
            await self._respond(
                send,
                429,
                {"error": "Rate limit exceeded"},
                headers=[(b"retry-after", str(retry_after).encode("ascii"))],
            )
            return
        await self.app(scope, receive, send)

    def _authorized_token(self, authorization: list[bytes]) -> bytes | None:
        if len(authorization) != 1:
            return None
        try:
            scheme, token_text = authorization[0].decode("latin-1").strip().split(None, 1)
        except ValueError:
            return None
        if scheme.lower() != "bearer" or not token_text.strip():
            return None
        candidate = token_text.strip().encode("utf-8")
        matched = False
        for expected in self.api_keys:
            matched = hmac.compare_digest(candidate, expected) or matched
        return candidate if matched else None

    @staticmethod
    async def _respond(send, status: int, body: dict[str, str], headers=None):
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        response_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("ascii")),
        ]
        response_headers.extend(headers or [])
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": response_headers,
        })
        await send({"type": "http.response.body", "body": payload})


def build_http_app(*, api_keys: list[str] | None = None,
                   requests_per_minute: int | None = None):
    """Build the authenticated Streamable HTTP ASGI application."""
    global _HTTP_MODE
    configured = api_keys
    if configured is None:
        raw = os.environ.get("SIMAPI_MCP_API_KEYS", "")
        configured = [item.strip() for item in raw.split(",") if item.strip()]
    if not configured:
        raise RuntimeError(
            "SIMAPI_MCP_API_KEYS must contain at least one bearer token before HTTP mode can start."
        )
    limit = requests_per_minute
    if limit is None:
        limit = _positive_env_int("SIMAPI_MCP_RATE_LIMIT", 60)
    elif limit < 1:
        raise ValueError("requests_per_minute must be a positive integer")
    security = mcp.settings.transport_security
    for env_name, field_name in (
        ("SIMAPI_MCP_ALLOWED_HOSTS", "allowed_hosts"),
        ("SIMAPI_MCP_ALLOWED_ORIGINS", "allowed_origins"),
    ):
        raw_values = os.environ.get(env_name)
        if raw_values is not None:
            values = [value.strip() for value in raw_values.split(",") if value.strip()]
            if not values:
                raise ValueError(f"{env_name} must be a comma-separated allowlist when set")
            setattr(security, field_name, values)
    _HTTP_MODE = True
    return MCPHTTPAuthRateLimit(
        mcp.streamable_http_app(),
        api_keys=configured,
        requests_per_minute=limit,
    )


if __name__ == "__main__":
    transport = os.environ.get("SIMAPI_MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "streamable-http":
        import uvicorn

        try:
            app = build_http_app()
        except (RuntimeError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        host = os.environ.get("SIMAPI_MCP_HOST", "127.0.0.1")
        port = _positive_env_int("SIMAPI_MCP_PORT", 8000)
        uvicorn.run(app, host=host, port=port)
    else:
        raise SystemExit(
            "Unsupported SIMAPI_MCP_TRANSPORT. Use 'stdio' or the authenticated 'streamable-http'."
        )
