"""Regression tests for ROS 2 bag message type normalization."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from core.kinematics import joint_signal_name
from integrations.ros2_loader import load_rosbag2


@pytest.mark.parametrize(
    ("connection_type", "expected_type"),
    [
        ("sensor_msgs/JointState", "sensor_msgs/msg/JointState"),
        ("sensor_msgs/msg/JointState", "sensor_msgs/msg/JointState"),
    ],
)
@pytest.mark.parametrize(
    ("joint_name", "expected_signal"),
    [
        ("joint1", "joint_1_position"),
        ("joint_1", "joint_1_position"),
        ("joint-1", "joint_1_position"),
    ],
)
def test_load_rosbag2_normalizes_joint_state_type_and_joint_names(
    tmp_path, monkeypatch, connection_type, expected_type, joint_name, expected_signal
):
    bag = tmp_path / "capture.mcap"
    bag.write_bytes(b"MCAP")
    connection = SimpleNamespace(
        topic="/arm/joint_states",
        msgtype=connection_type,
    )
    message = SimpleNamespace(
        name=[joint_name],
        position=[0.25],
        velocity=[],
        effort=[],
    )
    observed_types: list[str] = []

    class FakeReader:
        connections = [connection]

        def __init__(self, paths):
            assert paths == [bag]

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def messages(self, *, connections):
            assert connections == [connection]
            yield connection, 1_000_000_000, b"serialized"

        def deserialize(self, rawdata, msgtype):
            assert rawdata == b"serialized"
            observed_types.append(msgtype)
            return message

    rosbags = ModuleType("rosbags")
    rosbags.__path__ = []
    highlevel = ModuleType("rosbags.highlevel")
    highlevel.AnyReader = FakeReader
    rosbags.highlevel = highlevel
    monkeypatch.setitem(sys.modules, "rosbags", rosbags)
    monkeypatch.setitem(sys.modules, "rosbags.highlevel", highlevel)

    frame = load_rosbag2(bag, topic_hint="joint_states")

    assert observed_types == [expected_type]
    assert joint_signal_name(joint_name) == expected_signal
    assert frame.loc[0, expected_signal] == 0.25
