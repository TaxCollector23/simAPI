"""Unit declaration handling for revolute and prismatic robot joints."""

import pandas as pd
import pytest

from core.robotics_units import convert_robotics_inputs


def test_revolute_joint_positions_use_radians_or_degrees_but_not_meters():
    rows = [{"joint_shoulder_position": 180.0}]
    frame = pd.DataFrame(rows)
    converted, _, _, conversions = convert_robotics_inputs(
        frame, rows, {"joint_shoulder_position": "deg"}
    )

    assert converted.loc[0, "joint_shoulder_position"] == pytest.approx(3.141592653589793)
    assert conversions == {"joint_shoulder_position": "deg->rad"}
    with pytest.raises(ValueError, match="Unsupported unit 'm'"):
        convert_robotics_inputs(frame, rows, {"joint_shoulder_position": "m"})


def test_prismatic_joint_positions_and_velocities_require_urdf_joint_type():
    rows = [{"joint_slide_position": 0.25, "joint_slide_velocity": 0.5}]
    frame = pd.DataFrame(rows)
    linear = {"joint_slide_position", "joint_slide_velocity"}
    converted, _, _, conversions = convert_robotics_inputs(
        frame,
        rows,
        {"joint_slide_position": "m", "joint_slide_velocity": "m/s"},
        prismatic_signals=linear,
    )

    assert converted.loc[0, "joint_slide_position"] == pytest.approx(0.25)
    assert converted.loc[0, "joint_slide_velocity"] == pytest.approx(0.5)
    assert conversions == {
        "joint_slide_position": "m->m",
        "joint_slide_velocity": "m/s->m/s",
    }
    with pytest.raises(ValueError, match="Unsupported unit 'deg'"):
        convert_robotics_inputs(
            frame, rows, {"joint_slide_position": "deg"}, prismatic_signals=linear
        )


def test_prismatic_joint_effort_uses_newtons_and_converts_limit_units():
    rows = [{"joint_slide_effort": 5.0}]
    frame = pd.DataFrame(rows)
    converted, _, limits, conversions = convert_robotics_inputs(
        frame,
        rows,
        {"joint_slide_effort": "N"},
        {"joint_slide_effort": (-10.0, 10.0)},
        {"joint_slide_effort": "N"},
        prismatic_signals={"joint_slide_effort"},
    )

    assert converted.loc[0, "joint_slide_effort"] == pytest.approx(5.0)
    assert limits["joint_slide_effort"] == (-10.0, 10.0)
    assert conversions == {"joint_slide_effort": "n->N"}
    with pytest.raises(ValueError, match="Unsupported unit 'nm'"):
        convert_robotics_inputs(
            frame,
            rows,
            {"joint_slide_effort": "Nm"},
            prismatic_signals={"joint_slide_effort"},
        )


def test_revolute_joint_effort_still_uses_newton_metres():
    rows = [{"joint_elbow_effort": 5.0}]
    frame = pd.DataFrame(rows)
    converted, _, _, conversions = convert_robotics_inputs(
        frame, rows, {"joint_elbow_effort": "Nm"}
    )

    assert converted.loc[0, "joint_elbow_effort"] == pytest.approx(5.0)
    assert conversions == {}
    with pytest.raises(ValueError, match="Unsupported unit 'n'"):
        convert_robotics_inputs(frame, rows, {"joint_elbow_effort": "N"})
