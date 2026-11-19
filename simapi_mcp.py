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
import asyncio
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

from core.kinematics import parse_urdf_geometry  # noqa: E402
from core.physical_ai import _labels_from_checks  # noqa: E402
from core.robotics_engine import (  # noqa: E402
    DEFAULT_ROBOTICS_LIMITS,
    KinematicsSuite,
    RoboticsValidationEngine,
)
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
    "robotics_time_coverage": "No usable time column, so motion checks could not run. "
                              "Add a numeric 'time' column in seconds to every row.",
    "robotics_chatter": "High-frequency velocity oscillation (spectral FFT check). "
                        "The motion stays inside every static limit but oscillates above "
                        "chatter_min_frequency_hz — this burns out real actuators. Common "
                        "in simulated policies that never touched hardware.",
    "robotics_energy": "Kinetic energy changed between samples with no recorded effort "
                       "that can explain it — the signature of a physics-engine "
                       "contact-solver explosion. Fix the simulation, not the data.",
    "robotics_kinematics": "The reported end-effector position disagrees with forward "
                           "kinematics computed from the URDF and the joint positions.",
    "robotics_unprofiled_signal": "A signal was checked against very wide screening "
                                  "defaults only, not the robot's real limits. Pass "
                                  "robotics_limits (or a URDF) for a real verdict.",
    "robotics_not_evaluated": "A requested check could not run (missing signals, "
                              "non-uniform sampling, too few samples). This is a "
                              "fail-closed report, not a pass. See the check detail "
                              "for the exact reason.",
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


def _validate_dynamics_conditions(
    max_chatter_power_ratio: float | None,
    chatter_min_frequency_hz: float | None,
    energy_anomaly_factor: float | None,
) -> dict:
    """Validate and pack the optional dynamics-check conditions."""
    conditions: dict = {}
    if max_chatter_power_ratio is not None:
        if not (0 < max_chatter_power_ratio < 1):
            raise ValueError(
                "max_chatter_power_ratio must be between 0 and 1 — the fraction of "
                "velocity spectral power above chatter_min_frequency_hz that counts as "
                "actuator chatter. A good default is 0.25."
            )
        conditions["max_chatter_power_ratio"] = max_chatter_power_ratio
    if chatter_min_frequency_hz is not None:
        if not (chatter_min_frequency_hz > 0):
            raise ValueError(
                "chatter_min_frequency_hz must be a positive cutoff frequency in Hz "
                "(e.g. 10.0). It must stay below the episode's Nyquist frequency, "
                "1 / (2 * median sampling interval)."
            )
        conditions["chatter_min_frequency_hz"] = chatter_min_frequency_hz
    if energy_anomaly_factor is not None:
        if not (energy_anomaly_factor > 1):
            raise ValueError(
                "energy_anomaly_factor must be greater than 1 — how many times the "
                "episode's robust work/energy residual scale counts as an unexplained "
                "energy spike. A good default is 100."
            )
        conditions["energy_anomaly_factor"] = energy_anomaly_factor
    return conditions


_DYNAMICS_PARAMS_DOC = (
    "max_chatter_power_ratio / chatter_min_frequency_hz: optional actuator-chatter "
    "check (FFT spectral power on joint velocity). Flags windows whose power above "
    "chatter_min_frequency_hz (Hz) exceeds the ratio; ratio defaults to 0.25. "
    "Needs a numeric 'time' column (seconds) with near-uniform sampling and >= 16 samples.\n"
    "    energy_anomaly_factor: optional energy-conservation check. Flags intervals whose "
    "kinetic-energy change cannot be explained by recorded torque/effort work; needs "
    "joint velocities plus joint_N_torque or joint_N_effort. A good default is 100.\n"
)


def _run(rows: list[dict], robotics_limits: dict | None,
         max_time_step: float | None, velocity_tolerance: float | None,
         max_chatter_power_ratio: float | None = None,
         chatter_min_frequency_hz: float | None = None,
         energy_anomaly_factor: float | None = None) -> dict:
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
    conditions.update(_validate_dynamics_conditions(
        max_chatter_power_ratio, chatter_min_frequency_hz, energy_anomaly_factor
    ))
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
    max_chatter_power_ratio: float | None = None,
    chatter_min_frequency_hz: float | None = None,
    energy_anomaly_factor: float | None = None,
) -> dict:
    """Validate robot-arm trajectory data with SimAPI.

    rows: list of samples, one dict per moment in time, e.g.
          {"episode_id": "pick_cup_01", "time": 0.02,
           "joint_1_position": 0.02, "joint_1_velocity": 1.0, "joint_1_torque": 6.0}
          Positions in radians, velocities in rad/s, time in seconds. Multiple
          episodes per call are OK if each row has an episode_id.
    robotics_limits: allowed [min, max] per signal, e.g.
          {"joint_1_position": [-1.57, 1.57], "joint_1_torque": [-70, 70]}.
          Signals not listed fall back to very wide screening defaults.
    max_time_step: optional, seconds. Flag silent time gaps bigger than this.
    velocity_tolerance: optional, absolute. Also check that velocity implied by
          position changes agrees with the recorded velocity.
    """ + _DYNAMICS_PARAMS_DOC + """Returns verdict (passed/failed), the checks that
    failed, and the exact excluded rows with reasons. Use explain_robotics_check on
    any failed check name for a plain-English explanation and fix hint.
    """
    return _run(rows, robotics_limits, max_time_step, velocity_tolerance,
                max_chatter_power_ratio, chatter_min_frequency_hz, energy_anomaly_factor)


@mcp.tool()
def validate_robotics_csv(
    csv_path: str,
    robotics_limits: dict | None = None,
    max_time_step: float | None = None,
    velocity_tolerance: float | None = None,
    max_chatter_power_ratio: float | None = None,
    chatter_min_frequency_hz: float | None = None,
    energy_anomaly_factor: float | None = None,
) -> dict:
    """Validate a CSV file of robot trajectory data with SimAPI.

    The CSV needs one row per sample and columns like time (seconds),
    episode_id, joint_1_position (rad), joint_1_velocity (rad/s),
    joint_1_torque (Nm). Missing or non-numeric timestamps are reported as
    not-evaluated checks — add a numeric 'time' column so motion checks run.
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
    return _run(rows, robotics_limits, max_time_step, velocity_tolerance,
                max_chatter_power_ratio, chatter_min_frequency_hz, energy_anomaly_factor)


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
    max_chatter_power_ratio: float | None = None,
    chatter_min_frequency_hz: float | None = None,
    energy_anomaly_factor: float | None = None,
) -> dict:
    """Load a recording once, enforce the configured row cap, then validate it."""
    from integrations.lerobot_loader import load_lerobot
    from integrations.robotics_validation import validate_robotics_frame
    from integrations.ros2_loader import load_rosbag2

    limits, conditions = _limits_and_conditions(
        robotics_limits, max_time_step, velocity_tolerance,
        max_chatter_power_ratio, chatter_min_frequency_hz, energy_anomaly_factor,
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


def _limits_and_conditions(robotics_limits, max_time_step, velocity_tolerance,
                           max_chatter_power_ratio=None,
                           chatter_min_frequency_hz=None,
                           energy_anomaly_factor=None):
    conditions: dict = {}
    if max_time_step is not None:
        conditions["max_time_step"] = max_time_step
    if velocity_tolerance is not None:
        conditions["velocity_tolerance"] = velocity_tolerance
    conditions.update(_validate_dynamics_conditions(
        max_chatter_power_ratio, chatter_min_frequency_hz, energy_anomaly_factor
    ))
    return _validate_limits(robotics_limits), conditions


@mcp.tool()
def validate_recording(
    path: str,
    robotics_limits: dict | None = None,
    max_time_step: float | None = None,
    velocity_tolerance: float | None = None,
    topic_hint: str = "joint_states",
    max_episodes: int | None = None,
    max_chatter_power_ratio: float | None = None,
    chatter_min_frequency_hz: float | None = None,
    energy_anomaly_factor: float | None = None,
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
    """ + _DYNAMICS_PARAMS_DOC + """    topic_hint: ROS topic substring to read JointState messages from
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
        max_chatter_power_ratio,
        chatter_min_frequency_hz,
        energy_anomaly_factor,
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
    max_chatter_power_ratio: float | None = None,
    chatter_min_frequency_hz: float | None = None,
    energy_anomaly_factor: float | None = None,
) -> dict:
    """Validate an uploaded recording in HTTP mode.

    content_base64: base64-encoded bytes from one .parquet, .db3, .mcap or .zip file.
    filename: original file name; only its final path component is used.
    Same limits/conditions as validate_robotics_episode.
    """ + _DYNAMICS_PARAMS_DOC
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
            max_chatter_power_ratio,
            chatter_min_frequency_hz,
            energy_anomaly_factor,
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
    max_chatter_power_ratio: float | None = None,
    chatter_min_frequency_hz: float | None = None,
    energy_anomaly_factor: float | None = None,
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
    """ + _DYNAMICS_PARAMS_DOC + """
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
        result = _run(ep_rows, robotics_limits, max_time_step, velocity_tolerance,
                      max_chatter_power_ratio, chatter_min_frequency_hz,
                      energy_anomaly_factor)
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
def validate_and_filter_episodes(
    rows: list[dict],
    robotics_limits: dict | None = None,
    max_time_step: float | None = None,
    velocity_tolerance: float | None = None,
    max_chatter_power_ratio: float | None = None,
    chatter_min_frequency_hz: float | None = None,
    energy_anomaly_factor: float | None = None,
    urdf_xml: str | None = None,
    kinematics_tolerance_m: float = 0.01,
    min_workspace_z: float | None = None,
    min_self_collision_clearance_m: float | None = None,
    max_rejected_episodes: int = 5,
    run_id: str | None = None,
) -> dict:
    """Validate every episode and return ONLY the training-ready episode IDs.

    This is the one-call dataset filter for agents: it runs the FULL SimAPI
    robotics engine on each episode — scalar limits, trajectory motion
    checks, actuator chatter (FFT spectral check), energy conservation,
    humanoid contact checks, and, when urdf_xml is provided, URDF forward-
    kinematics consistency plus optional workspace-floor and capsule
    self-collision geometry checks.

    rows / robotics_limits / max_time_step / velocity_tolerance: same as
    validate_robotics_episode. Positions in radians, velocities in rad/s,
    effort in Nm (revolute) or N (prismatic), time in seconds.
    """ + _DYNAMICS_PARAMS_DOC + """
    urdf_xml: optional URDF XML string. When given, each episode is also
          checked against URDF forward kinematics (end-effector x/y/z columns,
          tolerance kinematics_tolerance_m in meters, default 0.01).
    kinematics_tolerance_m: end-effector position tolerance in meters.
    min_workspace_z: optional workspace floor in meters; FK tip positions
          below it fail the episode (catches floor clipping that joint
          limits alone cannot see).
    min_self_collision_clearance_m: optional minimum surface clearance in
          meters between non-adjacent link capsules (URDF cylinder/capsule
          collision geometry).
    max_rejected_episodes: how many rejected episodes to return inline
          (default 5, ranked worst-first). The full per-episode evidence for
          every episode is kept under the returned run_id — call
          get_episode_evidence for any episode not inlined here. This keeps
          large batches from overflowing the model context.
    run_id: optional caller-chosen identifier for the evidence store.

    Returns:
      training_ready_episodes: episode IDs whose checks all passed (safe to train on).
      rejected_episodes: the top max_rejected_episodes worst episodes, each
                           compact: {episode_id, samples, verdict,
                           failure_labels, failed_check_names}.
      rejected_episodes_total / omitted_rejected_episodes: full count and how
                           many were left out of the inline list.
      rejected_by_check: how many episodes each failing check removed.
      run_id: identifier for get_episode_evidence(run_id, episode_id).
      summary: episode/row counts in, ready, and rejected.
    """
    _enforce_row_cap(len(rows))
    if isinstance(max_rejected_episodes, bool) or not isinstance(max_rejected_episodes, int) \
            or max_rejected_episodes < 0:
        raise ValueError("max_rejected_episodes must be a non-negative integer.")
    if not rows:
        # Fail closed: nothing to validate is not a pass.
        return {
            "training_ready_episodes": [],
            "rejected_episodes": [{"episode_id": "(none)",
                                   "samples": 0, "verdict": "failed",
                                   "failure_labels": [],
                                   "failed_check_names": ["no_data"]}],
            "rejected_episodes_total": 1,
            "omitted_rejected_episodes": 0,
            "rejected_by_check": {"no_data": 1},
            "run_id": None,
            "summary": {"episodes_in": 0, "episodes_ready": 0, "episodes_rejected": 1,
                        "rows_in": 0, "rows_ready": 0},
        }
    conditions: dict = {}
    if max_time_step is not None:
        conditions["max_time_step"] = max_time_step
    if velocity_tolerance is not None:
        conditions["velocity_tolerance"] = velocity_tolerance
    conditions.update(_validate_dynamics_conditions(
        max_chatter_power_ratio, chatter_min_frequency_hz, energy_anomaly_factor
    ))
    limits = _validate_limits(robotics_limits)

    engine = RoboticsValidationEngine()
    if urdf_xml:
        if not (kinematics_tolerance_m >= 0) or kinematics_tolerance_m != kinematics_tolerance_m:
            raise ValueError("kinematics_tolerance_m must be a finite non-negative number in meters.")
        engine.suites.append(KinematicsSuite(
            parse_urdf_geometry(urdf_xml), tolerance_m=kinematics_tolerance_m,
            min_workspace_z=min_workspace_z,
            min_self_collision_clearance_m=min_self_collision_clearance_m,
        ))

    key = next((k for k in _EPISODE_KEYS if any(k in r for r in rows)), None)
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in rows:
        name = str(row.get(key, "(missing episode)")) if key else "Episode 1"
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append(row)

    ready: list[str] = []
    rejected: list[dict] = []
    rejected_by_check: dict[str, int] = {}
    rows_ready = 0
    evidence_by_episode: dict[str, dict] = {}
    for name in order:
        ep_rows = groups[name]
        report = check_robotics_limits(
            pd.DataFrame(ep_rows), limits, source_rows=ep_rows,
            conditions=conditions, engine=engine,
        )
        failed = [c for c in report["checks"] if c.get("status") == "failed"]
        warnings = [c for c in report["checks"] if c.get("status") == "warning"]
        flagged_rows = sorted(report.get("excluded") or {})
        evidence_by_episode[name] = {
            "episode_id": name,
            "samples": len(ep_rows),
            "verdict": "failed" if failed else "warning" if warnings else "passed",
            "failure_labels": _labels_from_checks(report["checks"]),
            "failed_checks": [
                {"name": c["name"], "detail": c.get("detail", "")} for c in failed
            ],
            "warning_checks": [
                {"name": c["name"], "detail": c.get("detail", "")} for c in warnings
            ],
            "flagged_sample_positions": flagged_rows[:200],
            "flagged_sample_count": len(flagged_rows),
            # On-demand inspection: the rows around the first violations.
            "first_violation_rows": [ep_rows[i] for i in flagged_rows[:5] if i < len(ep_rows)],
        }
        if not failed and not warnings:
            ready.append(name)
            rows_ready += len(ep_rows)
            continue
        for check in failed:
            rejected_by_check[check["name"]] = rejected_by_check.get(check["name"], 0) + 1
        rejected.append({
            "episode_id": name,
            "samples": len(ep_rows),
            "verdict": "failed" if failed else "warning",
            "failure_labels": _labels_from_checks(report["checks"]),
            "failed_checks": [
                {"name": c["name"], "detail": c.get("detail", "")} for c in failed
            ],
            "warning_checks": [
                {"name": c["name"], "detail": c.get("detail", "")} for c in warnings
            ],
        })

    # Context-safe pagination: worst episodes first (most failed checks, then
    # most samples), compacted to check names only.
    ranked = sorted(
        rejected,
        key=lambda episode: (-len(episode["failed_checks"]), -episode["samples"], episode["episode_id"]),
    )
    inline = [
        {
            "episode_id": episode["episode_id"],
            "samples": episode["samples"],
            "verdict": episode["verdict"],
            "failure_labels": episode["failure_labels"],
            "failed_check_names": [c["name"] for c in episode["failed_checks"]],
        }
        for episode in ranked[:max_rejected_episodes]
    ]
    stored_run_id = _store_evidence(run_id, evidence_by_episode, rows_ready)
    return {
        "training_ready_episodes": ready,
        "rejected_episodes": inline,
        "rejected_episodes_total": len(rejected),
        "omitted_rejected_episodes": max(0, len(rejected) - max_rejected_episodes),
        "rejected_by_check": rejected_by_check,
        "run_id": stored_run_id,
        "summary": {
            "episodes_in": len(order),
            "episodes_ready": len(ready),
            "episodes_rejected": len(rejected),
            "rows_in": len(rows),
            "rows_ready": rows_ready,
        },
        "detail": (
            f"Showing {len(inline)} of {len(rejected)} rejected episode(s); use "
            f"get_episode_evidence(run_id={stored_run_id!r}, episode_id=...) for "
            "any episode's full checks and offending samples."
            if len(rejected) > len(inline)
            else None
        ),
    }


# In-memory evidence store for on-demand episode inspection. Runs are capped
# so a hosted process cannot grow without bound; deployment is single-process.
_EVIDENCE_STORE: dict[str, dict] = {}
_EVIDENCE_STORE_MAX_RUNS = 64


def _store_evidence(run_id: str | None, evidence_by_episode: dict, rows_ready: int) -> str:
    """Register per-episode evidence under a run id (auto-generated if absent)."""
    import uuid

    stored = str(run_id) if run_id else f"run-{uuid.uuid4().hex[:12]}"
    if stored in _EVIDENCE_STORE and not run_id:
        stored = f"run-{uuid.uuid4().hex[:12]}"  # never silently overwrite
    _EVIDENCE_STORE[stored] = {
        "episodes": evidence_by_episode,
        "rows_ready": rows_ready,
    }
    while len(_EVIDENCE_STORE) > _EVIDENCE_STORE_MAX_RUNS:
        _EVIDENCE_STORE.pop(next(iter(_EVIDENCE_STORE)))
    return stored


@mcp.tool()
def get_episode_evidence(run_id: str, episode_id: str) -> dict:
    """Full evidence for one episode from a previous
    validate_and_filter_episodes run.

    Use this when the compact summary of validate_and_filter_episodes flags
    an episode you need to inspect: it returns the episode's verdict, failure
    labels, every failed/warning check with details, the flagged sample
    positions, and the first offending sample rows themselves.

    run_id: the identifier returned by validate_and_filter_episodes.
    episode_id: the episode to inspect (any episode from that run, including
                training-ready ones).
    """
    run = _EVIDENCE_STORE.get(str(run_id))
    if run is None:
        raise ValueError(
            f"Unknown run_id {run_id!r}. It may have expired from the evidence "
            "store; re-run validate_and_filter_episodes to get a fresh run_id."
        )
    evidence = run["episodes"].get(str(episode_id))
    if evidence is None:
        known = ", ".join(sorted(run["episodes"])[:20])
        raise ValueError(
            f"run_id {run_id!r} has no episode {episode_id!r}. Episodes in this run: {known}"
        )
    return evidence


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

    def __init__(self, app, api_keys: list[str], requests_per_minute: int,
                 firebase_key_validator=None):
        self.app = app
        self.api_keys = tuple(key.encode("utf-8") for key in api_keys)
        self.firebase_key_validator = firebase_key_validator
        self.requests_per_minute = requests_per_minute
        self._lock = threading.Lock()
        self._windows: dict[bytes, tuple[int, int]] = {}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("method") == "GET" and scope.get("path") == "/healthz":
            await self._respond(send, 200, {"status": "ok"})
            return

        authorization = [
            value for name, value in scope.get("headers", [])
            if name.lower() == b"authorization"
        ]
        token = self._authorized_token(authorization)
        if token is not None and not self._matches_static_key(token):
            if self.firebase_key_validator is None:
                token = None
            else:
                try:
                    valid = await asyncio.to_thread(self.firebase_key_validator, token.decode("utf-8"))
                except Exception:
                    valid = False
                if not valid:
                    token = None
        if token is None:
            await self._respond(
                send,
                401,
                {"error": "Unauthorized"},
                headers=[(b"www-authenticate", b'Bearer realm="SimAPI MCP"')],
            )
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
        return candidate

    def _matches_static_key(self, candidate: bytes) -> bool:
        matched = False
        for expected in self.api_keys:
            matched = hmac.compare_digest(candidate, expected) or matched
        return matched

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
    firebase_key_validator = _firebase_key_validator()
    if not configured and firebase_key_validator is None:
        raise RuntimeError(
            "SIMAPI_MCP_API_KEYS must contain at least one bearer token, or set SIMAPI_FIREBASE_SERVICE_ACCOUNT_JSON before HTTP mode can start."
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
        firebase_key_validator=firebase_key_validator,
    )


def _firebase_key_validator():
    """Return a fail-closed Firestore-backed validator when Admin credentials exist."""
    raw_credentials = os.environ.get("SIMAPI_FIREBASE_SERVICE_ACCOUNT_JSON", "")
    if not raw_credentials:
        return None
    try:
        from firebase_admin import credentials, firestore, get_app, initialize_app

        try:
            app = get_app()
        except ValueError:
            service_account = json.loads(raw_credentials)
            app = initialize_app(
                credentials.Certificate(service_account),
                {"projectId": service_account.get("project_id", "simapi-dev")},
            )
        collection = firestore.client(app=app).collection("mcpKeys")
    except Exception as exc:
        raise RuntimeError(
            "SIMAPI_FIREBASE_SERVICE_ACCOUNT_JSON is invalid or Firebase Admin could not initialize."
        ) from exc

    def validate(api_key: str) -> bool:
        if not api_key.startswith("sk_live_"):
            return False
        key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        snapshot = collection.document(key_hash).get()
        if not snapshot.exists:
            return False
        return snapshot.to_dict().get("revoked") is not True

    return validate


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
