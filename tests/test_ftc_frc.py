"""Built-in FTC/FRC profile checks on school robot telemetry."""
from pathlib import Path

import pandas as pd

from core.ftc_frc import FTC_DEFAULT_LIMITS, normalize_ftc_rows, validate_ftc_log


def test_ftc_fixture_flags_power_and_unwraps_heading():
    fixture = Path(__file__).parent / "fixtures" / "ftc-drive-log.csv"
    rows = pd.read_csv(fixture).to_dict(orient="records")

    report = validate_ftc_log(rows)

    assert report["verdict"] == "failed"
    assert [check["name"] for check in report["failed_checks"]] == ["power_range"]
    assert report["excluded_rows"] == {"1": ["left_motor_power=1.4 outside [-1, 1]"]}
    assert not any(check["name"] == "heading_jump" for check in report["failed_checks"])


def test_ftc_limits_can_be_overridden_and_common_headers_map():
    normalized = normalize_ftc_rows([{"Battery V": 12.2, "HeadingDeg": 10, "MotorPower": 0.25}])
    assert normalized == [{"battery_voltage": 12.2, "heading_deg": 10, "power": 0.25}]

    report = validate_ftc_log([{"time": 0, "motor_power": 1.4}], {"motor_power": (-2, 2)})
    assert report["verdict"] == "passed"
    assert FTC_DEFAULT_LIMITS["motor_power"] == (-1.0, 1.0)


def test_ftc_empty_or_unrecognized_logs_fail_closed():
    empty = validate_ftc_log([])
    unrecognized = validate_ftc_log([{"time": 0.0, "comment": "no telemetry"}])

    assert empty["verdict"] == "failed"
    assert empty["failed_checks"][0]["name"] == "no_data"
    assert unrecognized["verdict"] == "failed"
    assert unrecognized["failed_checks"][0]["name"] == "no_robot_signals"


def test_ftc_missing_time_caps_a_clean_range_pass_to_warning():
    report = validate_ftc_log([{"left_motor_power": 0.5}])

    assert report["verdict"] == "warning"
    assert report["warnings"][0]["name"] == "time_coverage"


def test_ftc_non_numeric_and_non_finite_recognized_signals_fail_closed():
    non_numeric = validate_ftc_log([{"time": 0.0, "left_motor_power": "not-a-number"}])
    non_finite = validate_ftc_log([{"time": 0.0, "heading_deg": float("nan")}])

    assert non_numeric["verdict"] == "failed"
    assert non_numeric["failed_checks"][0]["name"] == "invalid_numeric_signal"
    assert non_numeric["excluded_rows"] == {
        "0": ["left_motor_power is missing or non-finite/non-numeric"]
    }
    assert non_finite["verdict"] == "failed"
    assert non_finite["failed_checks"][0]["name"] == "invalid_numeric_signal"
