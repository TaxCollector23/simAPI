"""Upgraded kinematics: SO(3) hemisphere alignment, geodesic angular
velocity, URDF FK workspace floor, and link-capsule self-collision."""

import math

import numpy as np
import pytest

from core.kinematics import (
    align_quaternion_hemisphere,
    check_self_collision,
    check_workspace_floor,
    forward_kinematics_frames,
    geodesic_angular_velocity,
    parse_link_capsules,
    parse_urdf_geometry,
)
from core.robotics_engine import KinematicsSuite, RoboticsValidationEngine
from core.robotics_validation import check_robotics_limits

# A 2-link planar arm: base -> link1 (revolute about z) -> tool (revolute
# about y, so joint2 can fold the tool back over the arm). Capsules are
# cylinders with their axis rotated onto the chain direction.
TWO_LINK_URDF = """
<robot name="test_arm">
  <link name="base_link">
    <collision><origin xyz="0 0 -0.1"/>
      <geometry><cylinder radius="0.06" length="0.2"/></geometry></collision>
  </link>
  <link name="link1">
    <collision><origin xyz="0.25 0 0" rpy="0 1.5707963 0"/>
      <geometry><cylinder radius="0.05" length="0.5"/></geometry></collision>
  </link>
  <link name="tool">
    <collision><origin xyz="0.25 0 0" rpy="0 1.5707963 0"/>
      <geometry><cylinder radius="0.05" length="0.5"/></geometry></collision>
  </link>
  <joint name="joint1" type="revolute">
    <parent link="base_link"/><child link="link1"/>
    <origin xyz="0 0 0.1" rpy="0 0 0"/><axis xyz="0 0 1"/>
  </joint>
  <joint name="joint2" type="revolute">
    <parent link="link1"/><child link="tool"/>
    <origin xyz="0.5 0 0" rpy="0 0 0"/><axis xyz="0 1 0"/>
  </joint>
</robot>
"""


# -- SO(3) hemisphere alignment and geodesic angular velocity ------------------

def _constant_orientation_with_sign_flips():
    q = np.array([[0.0, 0.0, 0.0, 1.0],
                  [0.0, 0.0, 0.0, -1.0],
                  [0.0, 0.0, 0.0, 1.0],
                  [0.0, 0.0, 0.0, -1.0]])
    return q


def test_sign_flip_series_yields_zero_angular_velocity():
    times = np.arange(4) * 0.02
    speeds = geodesic_angular_velocity(_constant_orientation_with_sign_flips(), times)
    assert speeds == pytest.approx(0.0, abs=1e-12)


def test_alignment_puts_series_in_one_hemisphere():
    aligned = align_quaternion_hemisphere(_constant_orientation_with_sign_flips())
    assert all(float(aligned[i] @ aligned[i - 1]) >= 0.0 for i in range(1, len(aligned)))
    # q and -q encode the same rotation, so alignment must not change it.
    assert np.allclose(aligned, np.abs(aligned))


def test_true_rotation_yields_expected_angular_speed():
    times = np.arange(6) * 0.05
    angle = times * 2.0  # 2 rad/s about z
    quats = np.stack([
        np.zeros(len(times)), np.zeros(len(times)),
        np.sin(angle / 2.0), np.cos(angle / 2.0),
    ], axis=1)
    speeds = geodesic_angular_velocity(quats, times)
    assert speeds[1:] == pytest.approx(2.0, rel=1e-9)


def test_sign_flip_inside_real_rotation_does_not_spike():
    times = np.arange(8) * 0.05
    angle = times * 1.0
    quats = np.stack([
        np.zeros(len(times)), np.zeros(len(times)),
        np.sin(angle / 2.0), np.cos(angle / 2.0),
    ], axis=1)
    quats[4] = -quats[4]  # logger wrote one sample with the opposite sign
    speeds = geodesic_angular_velocity(quats, times)
    assert speeds[1:] == pytest.approx(1.0, rel=1e-9)


def test_geodesic_angular_velocity_rejects_bad_input():
    # A single sample is fine (speed 0); a repeated timestamp is not.
    assert geodesic_angular_velocity([[0, 0, 0, 1]], [0.0]) == pytest.approx([0.0])
    with pytest.raises(ValueError):
        geodesic_angular_velocity([[0, 0, 0, 1], [0, 0, 0, 1]], [0.0, 0.0])  # dt == 0
    with pytest.raises(ValueError):
        geodesic_angular_velocity([[0, 0, 0, 0], [0, 0, 0, 1]], [0.0, 0.1])  # zero norm


# -- workspace floor -----------------------------------------------------------

def _geometry():
    return parse_urdf_geometry(TWO_LINK_URDF)


def test_workspace_floor_violation_is_flagged():
    samples = [{"joint_1_position": 0.0, "joint_2_position": 0.0}]
    result = check_workspace_floor(_geometry(), samples, min_workspace_z=0.2)
    assert result["violations"] == [0]
    assert result["min_tip_z"] == pytest.approx(0.1, abs=1e-9)


def test_workspace_floor_passes_when_above():
    samples = [{"joint_1_position": 0.0, "joint_2_position": 0.0}]
    result = check_workspace_floor(_geometry(), samples, min_workspace_z=0.05)
    assert result["violations"] == []
    assert result["min_tip_z"] == pytest.approx(0.1, abs=1e-9)


def test_workspace_floor_rejects_non_finite_floor():
    with pytest.raises(ValueError):
        check_workspace_floor(_geometry(), [], min_workspace_z=float("nan"))


# -- capsule self-collision ----------------------------------------------------

def test_extended_arm_has_no_self_collision():
    capsules = parse_link_capsules(TWO_LINK_URDF)
    assert set(capsules) == {"base_link", "link1", "tool"}
    samples = [{"joint_1_position": 0.0, "joint_2_position": 0.0}]
    result = check_self_collision(_geometry(), capsules, samples,
                                  min_self_collision_clearance_m=0.05)
    assert result["violations"] == {}
    assert result["min_clearance_m"] > 0.05
    # base<->link1 and link1<->tool are adjacent; only base<->tool is checked.
    assert result["evaluated_pairs"] == 1


def test_folded_arm_self_collision_is_flagged():
    capsules = parse_link_capsules(TWO_LINK_URDF)
    # joint2 = pi folds the tool capsule back over the arm toward the base.
    samples = [{"joint_1_position": 0.0, "joint_2_position": math.pi}]
    result = check_self_collision(_geometry(), capsules, samples,
                                  min_self_collision_clearance_m=0.05)
    assert 0 in result["violations"]
    assert result["violations"][0] == ["base_link|tool"]


def test_self_collision_rejects_negative_clearance():
    with pytest.raises(ValueError):
        check_self_collision(_geometry(), {}, [], min_self_collision_clearance_m=-1.0)


# -- engine integration --------------------------------------------------------

def _rows(joint2=0.0, n=8):
    return [
        {"episode_id": "run", "time": i * 0.02,
         "joint_1_position": 0.0, "joint_2_position": joint2}
        for i in range(n)
    ]


def _report(rows, **suite_kwargs):
    import pandas as pd

    engine = RoboticsValidationEngine()
    engine.suites.append(KinematicsSuite(TWO_LINK_URDF, **suite_kwargs))
    return check_robotics_limits(
        pd.DataFrame(rows), source_rows=rows, engine=engine,
    )


def test_engine_flags_workspace_floor_violation():
    report = _report(_rows(), min_workspace_z=0.2)
    check = next(c for c in report["checks"] if c["name"].startswith("robotics_workspace_floor"))
    assert check["status"] == "failed"
    assert check["violations"] == len(_rows())
    assert report["summary"]["workspace_floor_violations"] == len(_rows())


def test_engine_flags_self_collision():
    report = _report(_rows(joint2=math.pi), min_self_collision_clearance_m=0.05)
    check = next(c for c in report["checks"] if c["name"].startswith("robotics_self_collision"))
    assert check["status"] == "failed"
    assert check["violations"] == len(_rows())
    assert report["summary"]["self_collision_violations"] == len(_rows())


def test_engine_self_collision_warns_without_collision_geometry():
    import pandas as pd

    stripped = TWO_LINK_URDF.replace("<collision>", "<ignored>").replace("</collision>", "</ignored>")
    engine = RoboticsValidationEngine()
    engine.suites.append(KinematicsSuite(stripped, min_self_collision_clearance_m=0.05))
    rows = _rows(0.0)
    report = check_robotics_limits(pd.DataFrame(rows), source_rows=rows, engine=engine)
    check = next(c for c in report["checks"] if c["name"].startswith("robotics_self_collision"))
    assert check["status"] == "warning"
    assert "no" in check["detail"].lower() or "not" in check["detail"].lower()


def test_geometry_checks_absent_when_not_requested():
    report = _report(_rows())
    assert not any(c["name"].startswith(("robotics_workspace_floor", "robotics_self_collision"))
                   for c in report["checks"])


def test_forward_kinematics_frames_covers_every_link():
    frames = forward_kinematics_frames(_geometry(), {"joint_1_position": 0.0, "joint_2_position": 0.0})
    assert set(frames) == {"base_link", "link1", "tool"}
    assert frames["tool"][0, 3] == pytest.approx(0.5)
    assert frames["tool"][2, 3] == pytest.approx(0.1)
