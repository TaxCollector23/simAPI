"""Import ROS 2 ``sensor_msgs/JointState`` bags into SimAPI's robotics engine.

Install the optional reader with ``pip install rosbags``. No ROS installation
is needed. Joint positions, velocities, and measured efforts retain their
distinct meanings; commanded actions are never inferred from effort.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from core.kinematics import normalize_joint_name
from integrations.recording_limits import RecordingSampleLimitExceeded
from integrations.robotics_validation import load_limits_profile, validate_robotics_frame

_JOINT_STATE_TYPES = {"sensor_msgs/msg/JointState", "sensor_msgs/JointState"}


def _rosbags_type_name(msgtype: str) -> str:
    """Normalize legacy ROS message names to rosbags' canonical form."""
    if msgtype == "sensor_msgs/JointState":
        return "sensor_msgs/msg/JointState"
    return msgtype


def _joint_stem(name: str) -> str:
    """Map a ROS joint name to a stable, collision-checkable signal prefix."""
    try:
        return normalize_joint_name(str(name))
    except ValueError as exc:
        raise ValueError("JointState contains an empty or invalid joint name") from exc


def _field_values(msg: Any, field: str, names: list[str]) -> list[Any]:
    values = getattr(msg, field, None)
    values = [] if values is None else list(values)
    if values and len(values) != len(names):
        raise ValueError(
            f"JointState {field} length ({len(values)}) does not match name length ({len(names)})"
        )
    return values


def _stamp_seconds(msg: Any, recorded_ns: int) -> float:
    try:
        stamp = msg.header.stamp
        header_time = float(stamp.sec) + float(stamp.nanosec) * 1e-9
        if math.isfinite(header_time) and header_time > 0:
            return header_time
    except (AttributeError, TypeError, ValueError):
        pass
    return float(recorded_ns) * 1e-9


def load_rosbag2(
    bag: str | Path,
    *,
    topic_hint: str = "joint_states",
    episode_every_s: float | None = None,
    max_rows: int | None = None,
) -> pd.DataFrame:
    """Read JointState messages into one row per message and episode.

    ``episode_id`` changes on a backwards timestamp reset and optionally at
    fixed-duration boundaries. A ``.db3`` path is accepted when its parent is
    a standard rosbag2 directory containing ``metadata.yaml``.
    """
    if episode_every_s is not None and (not math.isfinite(episode_every_s) or episode_every_s <= 0):
        raise ValueError("episode_every_s must be a finite positive number")
    if max_rows is not None and (isinstance(max_rows, bool) or max_rows < 1):
        raise ValueError("max_rows must be a positive integer or None")
    try:
        from rosbags.highlevel import AnyReader
    except ImportError as exc:
        raise RuntimeError("ROS 2 bag support requires the optional 'rosbags' package") from exc

    source = Path(bag).expanduser()
    if not source.exists():
        raise FileNotFoundError(source)
    # Modern rosbags can read a standalone rosbag2 storage file. When the
    # standard metadata file exists, point the reader at the whole bag folder
    # so relative_file_paths and other metadata remain authoritative.
    reader_path = source
    if source.is_file() and source.suffix.lower() == ".db3" and (source.parent / "metadata.yaml").is_file():
        reader_path = source.parent
    rows: list[dict[str, Any]] = []
    last_stamp: dict[str, float] = {}
    reset_index: dict[str, int] = {}
    first_stamp: dict[tuple[str, int], float] = {}
    canonical_by_topic: dict[str, dict[str, str]] = {}

    with AnyReader([reader_path]) as reader:
        connections = [
            conn for conn in reader.connections
            if conn.msgtype in _JOINT_STATE_TYPES
            and (not topic_hint or topic_hint.lower() in conn.topic.lower())
        ]
        if not connections:
            topics = sorted({conn.topic for conn in reader.connections})
            raise ValueError(
                f"No sensor_msgs/JointState topic matched {topic_hint!r}; available topics: {topics}"
            )

        for conn, recorded_ns, rawdata in reader.messages(connections=connections):
            msg = reader.deserialize(rawdata, _rosbags_type_name(conn.msgtype))
            names = [str(name) for name in (getattr(msg, "name", None) or [])]
            if not names:
                continue
            positions = _field_values(msg, "position", names)
            velocities = _field_values(msg, "velocity", names)
            efforts = _field_values(msg, "effort", names)
            timestamp = _stamp_seconds(msg, recorded_ns)
            topic = str(conn.topic)

            current_reset = reset_index.get(topic, 0)
            prior_stamp = last_stamp.get(topic)
            if prior_stamp is not None and timestamp < prior_stamp:
                current_reset += 1
                reset_index[topic] = current_reset
            last_stamp[topic] = timestamp
            reset_key = (topic, current_reset)
            start = first_stamp.setdefault(reset_key, timestamp)
            segment = int((timestamp - start) // episode_every_s) if episode_every_s else 0
            episode_id = f"{topic}:reset{current_reset}:segment{segment}"

            name_mapping = canonical_by_topic.setdefault(topic, {})
            stems: list[str] = []
            used: dict[str, str] = {value: key for key, value in name_mapping.items()}
            for name in names:
                stem = name_mapping.setdefault(name, _joint_stem(name))
                other_name = used.get(stem)
                if other_name is not None and other_name != name:
                    raise ValueError(
                        f"Joint names {other_name!r} and {name!r} normalize to the same SimAPI signal {stem!r}"
                    )
                used[stem] = name
                stems.append(stem)

            row: dict[str, Any] = {"episode_id": episode_id, "t": timestamp}
            for index, stem in enumerate(stems):
                if positions:
                    row[f"{stem}_position"] = float(positions[index])
                if velocities:
                    row[f"{stem}_velocity"] = float(velocities[index])
                if efforts:
                    row[f"{stem}_effort"] = float(efforts[index])
            if max_rows is not None and len(rows) >= max_rows:
                raise RecordingSampleLimitExceeded(len(rows) + 1, max_rows)
            rows.append(row)

    if not rows:
        raise ValueError(f"No JointState messages with named joints were found in {reader_path}")
    return pd.DataFrame(rows).sort_values(["episode_id", "t"], kind="stable").reset_index(drop=True)


def validate_rosbag2(
    bag: str | Path,
    *,
    limits: dict[str, tuple[float, float]] | None = None,
    conditions: dict[str, float] | None = None,
    topic_hint: str = "joint_states",
    episode_every_s: float | None = None,
) -> dict[str, Any]:
    frame = load_rosbag2(bag, topic_hint=topic_hint, episode_every_s=episode_every_s)
    result = validate_robotics_frame(frame, limits=limits, conditions=conditions, time_unit="seconds")
    result["source"] = str(bag)
    result["format"] = "rosbag2"
    return result


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m integrations.ros2_loader")
    parser.add_argument("bag", help="rosbag2 directory or a .db3 inside it")
    parser.add_argument("--topic-hint", default="joint_states")
    parser.add_argument("--episode-every-s", type=float, default=None)
    parser.add_argument("--out", default="", help="Write normalized robot rows to CSV")
    parser.add_argument("--report", default="")
    parser.add_argument("--profile", help="Limits JSON file in API robotics_limits format")
    args = parser.parse_args(argv)
    try:
        limits = load_limits_profile(args.profile)
    except (OSError, ValueError) as exc:
        parser.error(f"Invalid --profile: {exc}")
    frame = load_rosbag2(args.bag, topic_hint=args.topic_hint, episode_every_s=args.episode_every_s)
    report = validate_robotics_frame(frame, limits=limits)
    report.update({"source": str(args.bag), "format": "rosbag2"})
    if args.out:
        frame.to_csv(args.out, index=False)
    rendered = json.dumps(report, indent=2, default=str)
    print(rendered)
    if args.report:
        Path(args.report).write_text(rendered + "\n", encoding="utf-8")
    return 1 if not report["training_ready"] else 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
