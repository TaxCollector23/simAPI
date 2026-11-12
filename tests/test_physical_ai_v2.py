"""Regression tests for Physical-AI profiles and dataset-quality helpers."""

import math

import pytest

from core.physical_ai_v2 import (
    ARM_PROFILES,
    GENERIC_PROFILE_NAME,
    check_jerk,
    cluster_failures,
    convert_degrees_to_radians,
    dataset_health_score,
    detect_units,
    get_profile,
    torque_saturation_trend,
    validate_guarded,
)


def test_profiles_expand_to_the_requested_joint_count_and_are_screening_values():
    limits = get_profile("franka_panda", 2)
    assert len(limits) == 8
    assert limits["joint_1_torque"] == (-87.0, 87.0)
    assert limits["joint_2_velocity"] == (-2.175, 2.175)
    assert get_profile(GENERIC_PROFILE_NAME)["joint_1_position"] == (
        -2 * math.pi,
        2 * math.pi,
    )
    assert set(ARM_PROFILES) == {
        "franka_panda", "ur5e", "ur10e", "xarm7", "so101", "generic_lab_arm"
    }


def test_profiles_use_joint_specific_limits_instead_of_the_largest_joint_bound():
    franka = get_profile("franka_panda", 7)
    ur5e = get_profile("ur5e", 6)
    ur10e = get_profile("ur10e", 6)
    xarm7 = get_profile("xarm7", 7)

    assert franka["joint_5_torque"] == (-12.0, 12.0)
    assert franka["joint_4_position"] == (-3.0718, -0.0698)
    assert ur5e["joint_4_torque"] == (-28.0, 28.0)
    assert ur10e["joint_6_torque"] == (-56.0, 56.0)
    assert xarm7["joint_6_torque"] == (-30.6, 30.6)


def test_unknown_profile_is_rejected_with_known_names():
    with pytest.raises(ValueError, match="Known profiles"):
        get_profile("made_up_arm")


def test_guard_uses_generic_screening_profile_and_never_calls_it_training_ready():
    rows = [
        {"episode_id": "e1", "t": 0.0, "joint_1_position": 0.1, "joint_1_torque": 2.0},
        {"episode_id": "e1", "t": 0.1, "joint_1_position": 0.2, "joint_1_torque": 3.0},
    ]

    report = validate_guarded(rows)

    assert report["limits_source"] == "screening_profile"
    assert report["profile_used"] == GENERIC_PROFILE_NAME
    assert report["limits_used"]["joint_1_torque"] == (-150.0, 150.0)
    assert any(check["name"] == "profile_guard" and check["status"] == "warning"
               for check in report["checks"])
    assert report["verdict"] == "warning"
    assert report["training_ready"] is False


def test_guard_fails_loudly_on_impossible_torque_and_allow_defaults_still_warns():
    rows = [{"joint_1_torque": 50_000.0}]
    screened = validate_guarded(rows)
    limit_failure = next(c for c in screened["checks"]
                         if c["name"] == "robotics_limit:joint_1_torque")
    assert limit_failure["status"] == "failed"
    assert screened["excluded"]
    assert screened["verdict"] == "failed"
    assert screened["training_ready"] is False

    raw = validate_guarded([{"joint_1_torque": 5.0}], allow_defaults=True)
    assert raw["limits_source"] == "core_defaults"
    assert any(c["name"] == "profile_guard" for c in raw["checks"])
    assert raw["training_ready"] is False


def test_generic_screening_bounds_cover_high_and_named_joint_signals():
    report = validate_guarded([{
        "joint_8_torque": 50_000.0,
        "joint_elbow_torque": 50_000.0,
    }])

    for signal in ("joint_8_torque", "joint_elbow_torque"):
        assert report["limits_used"][signal] == (-150.0, 150.0)
        check = next(
            c for c in report["checks"]
            if c["name"] == f"robotics_limit:{signal}"
        )
        assert check["status"] == "failed"
    assert report["verdict"] == "failed"
    assert report["training_ready"] is False


def test_explicit_generic_profile_remains_screening_only():
    impossible = validate_guarded(
        [{"joint_8_torque": 50_000.0}], profile=GENERIC_PROFILE_NAME
    )
    assert impossible["limits_used"]["joint_8_torque"] == (-150.0, 150.0)
    assert any(
        c["name"] == "robotics_limit:joint_8_torque" and c["status"] == "failed"
        for c in impossible["checks"]
    )
    assert any(
        c["name"] == "profile_guard" and c["status"] == "warning"
        for c in impossible["checks"]
    )
    assert impossible["training_ready"] is False

    report = validate_guarded(
        [{"joint_elbow_torque": 5.0}], profile=GENERIC_PROFILE_NAME
    )

    assert report["limits_used"]["joint_elbow_torque"] == (-150.0, 150.0)
    assert any(
        c["name"] == "profile_guard" and c["status"] == "warning"
        for c in report["checks"]
    )
    assert report["verdict"] == "warning"
    assert report["training_ready"] is False


def test_guard_respects_explicit_limits_and_named_profiles_without_guard_warning():
    explicit = validate_guarded(
        [{"joint_1_torque": 95.0}],
        limits={"joint_1_torque": (-70.0, 70.0)},
    )
    assert explicit["limits_source"] == "explicit"
    assert any(c["name"] == "robotics_limit:joint_1_torque"
               and c["status"] == "failed" for c in explicit["checks"])
    assert not any(c["name"] == "profile_guard" for c in explicit["checks"])

    profiled = validate_guarded(
        [{"joint_1_torque": 20.0}], profile="franka_panda"
    )
    assert profiled["limits_source"] == "profile"
    assert profiled["limits_used"]["joint_1_torque"] == (-87.0, 87.0)
    assert not any(c["name"] == "profile_guard" for c in profiled["checks"])


def test_partial_robot_limits_are_disclosed_and_effort_gets_torque_profile():
    rows = [{"joint_1_torque": 2.0, "joint_1_velocity": 0.5}]
    explicit = validate_guarded(
        rows, limits={"joint_1_torque": (-10.0, 10.0)}
    )
    profiled = validate_guarded(
        [{"joint_1_effort": 200.0}], profile=GENERIC_PROFILE_NAME
    )

    assert explicit["verdict"] == "warning"
    assert explicit["training_ready"] is False
    assert any("joint_1_velocity" in c["detail"] for c in explicit["checks"])
    assert profiled["verdict"] == "failed"
    assert profiled["limits_used"]["joint_1_effort"] == (-150.0, 150.0)


def test_row_based_profile_limits_keep_joint_specific_bounds():
    report = validate_guarded(
        [{"joint_5_torque": 20.0}], profile="franka_panda"
    )

    assert report["verdict"] == "failed"
    assert report["limits_used"]["joint_5_torque"] == (-12.0, 12.0)


def test_guard_fails_closed_for_empty_rows_and_rejects_bad_limits_by_signal():
    empty = validate_guarded([])
    assert empty["verdict"] == "failed"
    assert empty["training_ready"] is False
    assert empty["checks"][0]["name"] == "no_data"

    for bounds in ([1.0], [2.0, 1.0], [math.nan, 1.0], [0.0, math.inf]):
        with pytest.raises(ValueError, match="joint_1_torque"):
            validate_guarded(
                [{"joint_1_torque": 0.0}],
                limits={"joint_1_torque": bounds},
            )


def test_extra_joints_outside_a_profiles_dof_count_are_not_silently_profiled():
    report = validate_guarded([{"joint_8_torque": 1.0}], profile="ur5e")

    assert report["verdict"] == "warning"
    assert report["training_ready"] is False
    assert any("joint_8_torque" in c["detail"] for c in report["checks"])


def test_jerk_check_flags_cubic_position_motion_at_global_endpoint_rows():
    rows = [
        {"episode_id": "one", "t": float(i), "joint_1_position": float(i**3)}
        for i in range(6)
    ]

    report = check_jerk(rows, max_jerk=5.0)

    assert report["verdict"] == "failed"
    assert report["flagged_rows"] == [3, 4, 5]
    assert report["excluded"] == {
        3: ["jerk 6.0 rad/s^3 exceeds ±5 (from joint_1_position)"],
        4: ["jerk 6.0 rad/s^3 exceeds ±5 (from joint_1_position)"],
        5: ["jerk 6.0 rad/s^3 exceeds ±5 (from joint_1_position)"],
    }


def test_jerk_check_does_not_compare_across_episode_boundaries():
    rows = [
        {"episode_id": "a", "t": 0.0, "joint_1_position": 0.0},
        {"episode_id": "a", "t": 0.1, "joint_1_position": 0.0},
        {"episode_id": "b", "t": 0.0, "joint_1_position": 10_000.0},
        {"episode_id": "b", "t": 0.1, "joint_1_position": 10_000.0},
    ]

    report = check_jerk(rows, max_jerk=1.0)

    assert report["verdict"] == "warning"
    assert report["excluded"] == {}
    assert report["flagged_rows"] == []


def test_units_detection_and_conversion_preserve_original_rows():
    rows = [
        {"joint_1_position": 0.0, "tag": "start"},
        {"joint_1_position": 90.0, "tag": "middle"},
        {"joint_1_position": 360.0, "tag": "end"},
        {"joint_2_position": 2 * math.pi, "tag": "radians"},
        {"joint_3_position": 361.0, "tag": "too_large_for_degree_guess"},
    ]

    report = detect_units(rows)
    converted = convert_degrees_to_radians(rows)

    assert report["likely_degree_signals"] == ["joint_1_position"]
    assert report["suspicious_signals"] == ["joint_3_position"]
    assert report["verdict"] == "warning"
    assert report["signals"]["joint_2_position"]["likely_degrees"] is False
    assert converted[1]["joint_1_position"] == pytest.approx(math.pi / 2)
    assert converted[2]["joint_1_position"] == pytest.approx(2 * math.pi)
    assert converted[3]["joint_2_position"] == 2 * math.pi
    assert rows[1]["joint_1_position"] == 90.0
    assert converted[1] is not rows[1]


def test_health_score_uses_70_30_weights_and_empty_input_is_zero_f():
    report = dataset_health_score({"episodes": [
        {"samples": 10, "training_ready": True, "failure_labels": [], "flagged_rows": []},
        {"samples": 10, "training_ready": False, "failure_labels": ["teleport"],
         "flagged_rows": [10, 11]},
    ]})
    assert report["score"] == 62
    assert report["band"] == "C"
    assert report["training_ready_episodes"] == 1
    assert report["total_rows"] == 20
    assert report["flagged_rows"] == 2
    assert any("teleport" in reason for reason in report["reasons"])

    empty = dataset_health_score([])
    assert empty["score"] == 0
    assert empty["band"] == "F"
    assert empty["episodes"] == 0


def test_health_score_handles_unhashable_flagged_row_values():
    report = dataset_health_score([{
        "samples": 2,
        "training_ready": False,
        "flagged_rows": [{"row": 1}, {"row": 2}],
    }])
    assert report["flagged_rows"] == 2


def test_failure_clustering_groups_by_label_and_signal_with_plain_names():
    failures = [
        {"name": "robotics_limit:joint_1_torque", "row": index}
        for index in range(8)
    ] + [
        {"label": "time_gap", "signal": "t", "flagged_rows": [20, 21]},
    ]

    report = cluster_failures(failures)

    assert report["total_failures"] == 10
    assert report["verdict"] == "failed"
    first, second = report["clusters"]
    assert first["label"] == "robotics_limit"
    assert first["signal"] == "joint_1_torque"
    assert first["count"] == 8
    assert len(first["example_rows"]) == 5
    assert second["count"] == 2
    assert first["name_plain"] == "Value outside its allowed range — joint_1_torque"
    assert second["name_plain"] == "Hole in the timestamps — t"


def test_failure_clusters_ignore_passed_checks_and_use_violation_counts():
    report = cluster_failures([
        {"name": "robotics_limit:joint_1_torque", "status": "passed", "violations": 0},
        {"name": "robotics_limit:joint_1_torque", "status": "failed", "violations": 214},
    ])
    assert report["total_failures"] == 214
    assert len(report["clusters"]) == 1
    assert report["clusters"][0]["count"] == 214


def test_torque_saturation_trend_reports_increasing_fraction_and_short_data():
    rows = [{"joint_1_torque": float(value)} for value in (0, 5, 10, 20, 95, 97, 99, 100)]

    trend = torque_saturation_trend(rows, "joint_1_torque", (-100.0, 100.0))
    short = torque_saturation_trend(rows[:3], "joint_1_torque", 100.0)

    assert trend["first_half_fraction"] == 0.0
    assert trend["second_half_fraction"] == 1.0
    assert trend["delta"] == 1.0
    assert trend["trend"] == "increasing"
    assert short["trend"] == "unknown"
