"""URDF FK math and suite integration tests."""
import math

import pandas as pd
import pytest

from core.kinematics import (
    forward_kinematics,
    joint_signal_name,
    parse_urdf_geometry,
)
from core.robotics_engine import KinematicsSuite, RoboticsValidationEngine
from core.robotics_validation import check_robotics_limits
from integrations.ros2_loader import _joint_stem

TWO_LINK_URDF = """
<robot name="two_link_planar">
  <link name="base" />
  <link name="upper_arm" />
  <link name="forearm" />
  <link name="hand" />
  <joint name="shoulder" type="revolute">
    <parent link="base" /><child link="upper_arm" />
    <origin xyz="0 0 0" rpy="0 0 0" /><axis xyz="0 0 1" />
  </joint>
  <joint name="elbow" type="revolute">
    <parent link="upper_arm" /><child link="forearm" />
    <origin xyz="1 0 0" rpy="0 0 0" /><axis xyz="0 0 1" />
  </joint>
  <joint name="hand_mount" type="fixed">
    <parent link="forearm" /><child link="hand" />
    <origin xyz="1 0 0" rpy="0 0 0" />
  </joint>
</robot>
"""


def _signals():
    return {
        "shoulder": joint_signal_name("shoulder"),
        "elbow": joint_signal_name("elbow"),
    }


def test_two_link_planar_fk_matches_hand_computed_positions():
    geometry = parse_urdf_geometry(TWO_LINK_URDF)
    signals = _signals()
    cases = [
        ((0.0, 0.0), (2.0, 0.0, 0.0)),
        ((math.pi / 2, 0.0), (0.0, 2.0, 0.0)),
        ((0.0, math.pi / 2), (1.0, 1.0, 0.0)),
    ]

    for (shoulder, elbow), expected in cases:
        actual = forward_kinematics(
            geometry,
            {signals["shoulder"]: shoulder, signals["elbow"]: elbow},
            signals,
        )
        assert actual == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("joint_name", ["joint1", "joint_1", "joint-1"])
def test_ros_numbered_joint_names_match_urdf_fk_signals(joint_name):
    urdf = f"""
    <robot name="numbered_joint">
      <link name="base" /><link name="tool" />
      <joint name="{joint_name}" type="revolute">
        <parent link="base" /><child link="tool" />
        <axis xyz="0 0 1" />
      </joint>
    </robot>
    """
    ros_signal = f"{_joint_stem(joint_name)}_position"
    rows = [
        {
            ros_signal: 0.0,
            "end_effector_x": 0.0,
            "end_effector_y": 0.0,
            "end_effector_z": 0.0,
        }
    ]

    report = RoboticsValidationEngine().validate(
        pd.DataFrame(rows),
        source_rows=rows,
        additional_suites=[KinematicsSuite(urdf)],
    )

    coverage = next(
        (check for check in report["checks"] if check["name"] == "robotics_kinematics:coverage"),
        None,
    )
    fk_check = next(
        check for check in report["checks"] if check["name"] == "robotics_kinematics:end_effector_position"
    )
    assert coverage is None
    assert fk_check["status"] == "passed"
    assert report["summary"]["kinematics"]["coverage"] == 1.0


def test_kinematics_suite_excludes_wrong_reported_hand_position_and_adds_evidence():
    signals = _signals()
    rows = [{
        "episode_id": "pick-1",
        "time": 0.25,
        signals["shoulder"]: 0.0,
        signals["elbow"]: 0.0,
        "end_effector_x": 0.0,
        "end_effector_y": 0.0,
        "end_effector_z": 0.0,
    }]
    suite = KinematicsSuite(parse_urdf_geometry(TWO_LINK_URDF), signals, tolerance_m=0.01)

    report = RoboticsValidationEngine().validate(
        pd.DataFrame(rows), source_rows=rows, additional_suites=[suite]
    )

    check = next(c for c in report["checks"] if c["name"] == "robotics_kinematics:end_effector_position")
    evidence = next(e for e in report["evidence"]["entries"] if e["check"] == check["name"])
    assert check["status"] == "failed"
    assert check["indices"] == [0]
    assert report["excluded"] == {
        0: ["Reported end-effector position differs from URDF forward kinematics by 2 m, above the 0.01 m tolerance."]
    }
    assert evidence["computed_position"] == pytest.approx({"x": 2.0, "y": 0.0, "z": 0.0})
    assert evidence["reported_position"] == {"x": 0.0, "y": 0.0, "z": 0.0}
    assert evidence["distance_m"] == pytest.approx(2.0)
    assert evidence["episode_id"] == "pick-1"
    assert evidence["time"] == pytest.approx(0.25)


def test_kinematics_uses_full_position_column_alias_and_skips_missing_hand_data():
    signals = _signals()
    rows = [
        {
            signals["shoulder"]: 0.0,
            signals["elbow"]: 0.0,
            "end_effector_position_x": 2.0,
            "end_effector_position_y": 0.0,
            "end_effector_position_z": 0.0,
        },
        {signals["shoulder"]: 0.0, signals["elbow"]: 0.0},
    ]
    report = check_robotics_limits(
        pd.DataFrame(rows),
        source_rows=rows,
        additional_suites=[KinematicsSuite(TWO_LINK_URDF, signals)],
    )

    check = next(c for c in report["checks"] if c["name"] == "robotics_kinematics:end_effector_position")
    assert check["status"] == "passed"
    assert check["indices"] == []
    assert check["violations"] == 0
    coverage = next(c for c in report["checks"] if c["name"] == "robotics_kinematics:coverage")
    assert coverage["status"] == "warning"
    assert coverage["indices"] == [1]
    assert report["excluded"][1][0].startswith("URDF FK could not run")
    assert report["summary"]["kinematics"] == {
        "evaluated_rows": 1,
        "skipped_rows": 1,
        "total_rows": 2,
        "coverage": 0.5,
        "tolerance_m": 0.01,
    }


def test_missing_hand_columns_warn_and_exclude_unchecked_rows():
    rows = [{"joint_shoulder_position": 0.0, "joint_elbow_position": 0.0}]
    baseline = RoboticsValidationEngine().validate(pd.DataFrame(rows), source_rows=rows)
    with_optional_suite = RoboticsValidationEngine().validate(
        pd.DataFrame(rows),
        source_rows=rows,
        additional_suites=[KinematicsSuite(TWO_LINK_URDF, _signals())],
    )

    assert with_optional_suite != baseline
    coverage = next(c for c in with_optional_suite["checks"] if c["name"] == "robotics_kinematics:coverage")
    assert coverage["status"] == "warning"
    assert coverage["indices"] == [0]
    assert with_optional_suite["summary"]["kinematics"]["coverage"] == 0.0
    assert 0 in with_optional_suite["excluded"]


def test_default_engine_output_is_unchanged_with_empty_optional_suites():
    rows = [{"time": 0.0, "joint_1_position": 0.1}]
    frame = pd.DataFrame(rows)
    engine = RoboticsValidationEngine()

    assert engine.validate(frame, source_rows=rows) == engine.validate(
        frame, source_rows=rows, additional_suites=[]
    )


def test_parser_requires_an_unambiguous_chain_or_explicit_links():
    branched = """
    <robot name="branch">
      <link name="base" /><link name="left" /><link name="right" />
      <joint name="left_joint" type="fixed"><parent link="base"/><child link="left"/></joint>
      <joint name="right_joint" type="fixed"><parent link="base"/><child link="right"/></joint>
    </robot>
    """
    with pytest.raises(ValueError, match="one tip link"):
        parse_urdf_geometry(branched)
    geometry = parse_urdf_geometry(branched, base_link="base", tip_link="left")
    assert geometry.tip_link == "left"
    assert forward_kinematics(geometry, {}) == pytest.approx((0.0, 0.0, 0.0))


def test_parser_rejects_multi_parent_graphs_and_entity_declarations():
    multi_parent = """<robot name="multi_parent">
      <link name="base"/><link name="left"/><link name="right"/><link name="tip"/>
      <joint name="left_joint" type="fixed"><parent link="base"/><child link="left"/></joint>
      <joint name="right_joint" type="fixed"><parent link="base"/><child link="right"/></joint>
      <joint name="left_tip" type="fixed"><parent link="left"/><child link="tip"/></joint>
      <joint name="right_tip" type="fixed"><parent link="right"/><child link="tip"/></joint>
    </robot>"""
    entity_xml = """<!DOCTYPE robot [<!ENTITY name "unsafe">]>
    <robot name="&name;"><link name="base"/></robot>"""

    with pytest.raises(ValueError, match="more than one parent joint"):
        parse_urdf_geometry(multi_parent)
    with pytest.raises(ValueError, match="DTD and entity declarations"):
        parse_urdf_geometry(entity_xml)


def test_kinematics_suite_enforces_evaluation_cap():
    rows = [{"joint_shoulder_position": 0.0}, {"joint_shoulder_position": 0.1}]
    suite = KinematicsSuite(TWO_LINK_URDF, _signals(), max_evaluations=1)

    with pytest.raises(ValueError, match="limited to 1 sample"):
        RoboticsValidationEngine().validate(
            pd.DataFrame(rows), source_rows=rows, additional_suites=[suite]
        )
