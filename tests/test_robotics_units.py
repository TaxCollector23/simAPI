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
