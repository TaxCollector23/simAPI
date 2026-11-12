"""
ftc_frc.py — SimAPI-style validation for school robotics logs (FTC / FRC).

Standalone: standard library only, no SimAPI import needed.
Drop it into the SimAPI repo at:  core/ftc_frc.py   (or use it on its own)

School robots (FIRST Tech Challenge / FIRST Robotics Competition) don't
log robot-arm columns like joint_1_position. They log things like:

    time, left_power, right_power, left_encoder_position,
    left_encoder_velocity, battery_voltage, heading_deg, x, y

  - motor power is a number from -1 (full reverse) to 1 (full forward)
  - encoders count wheel/motor turns ("ticks")
  - heading_deg is the gyro compass angle: it wraps around, so after
    +179 degrees comes -179 degrees — that is a tiny 2-degree turn,
    NOT a teleport.

But the same *lies* show up as in big-robot data, and this module checks
for them, in the same report shape as the rest of SimAPI:

    {"verdict": "passed"/"failed",
     "failed_checks": [{"name": ..., "detail": ...}, ...],
     "warnings": [...],
     "excluded_rows": {"12": ["reasons..."]},
     "episodes": [{"episode_id": ..., "samples": n, "flagged_samples": m}]}

Checks
------
  power_range            any *_power value outside [-1, 1]
  encoder_velocity       speed implied by encoder positions disagrees with
                         the reported *_velocity column
  motion_without_power   encoder moves fast while motor power is ~0
                         (pushed? slipped? encoder glitch?)
  battery_sag            battery voltage drops low WHILE the motors are
                         working hard (weak battery / bad wiring)
  heading_jump           compass jumps more than 90 degrees in one step
                         (after unwrap — the +179 -> -179 wrap is fine)
  odometry_jump          x/y position implies a speed above the max
"""

from __future__ import annotations

import math
import re
import statistics
from typing import Any

__all__ = ["FTC_DEFAULT_LIMITS", "normalize_ftc_rows", "validate_ftc_log"]

# Ranges a normal FTC robot lives in. battery_voltage is a WARN band:
# outside it is worth knowing, but it is not automatically "bad data".
FTC_DEFAULT_LIMITS: dict[str, Any] = {
    "motor_power": (-1.0, 1.0),
    "battery_voltage": (10.5, 14.5),   # warn band
    "battery_sag_voltage": 12.0,       # below this, under heavy load = sag
    "sag_min_total_power": 2.0,        # sum of |power| that counts as "hard work"
    "velocity_tolerance": 50.0,        # ticks/sec disagreement allowed
    "min_moving_speed": 50.0,          # ticks/sec that counts as "moving"
    "max_speed": 100.0,                # odometry units/sec (inches, cm — your units)
    "heading_jump_deg": 90.0,
}

TIME_KEYS = ("time", "t", "timestamp", "elapsed_time")
EPISODE_KEYS = ("episode_id", "episode", "match", "segment")


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def _find_key(row: dict[str, Any], candidates) -> str | None:
    for key in candidates:
        if key in row:
            return key
    return None


def _median_dt(rows: list[dict[str, Any]], time_key: str) -> float | None:
    """Median gap between consecutive timestamps, or None when there is
    not a single usable pair (e.g. a log with no time values at all —
    that must report None, not crash)."""
    dts = []
    for i in range(1, len(rows)):
        t0 = _num(rows[i - 1].get(time_key))
        t1 = _num(rows[i].get(time_key))
        if t0 is not None and t1 is not None:
            dts.append(t1 - t0)
    return statistics.median(dts) if dts else None


def normalize_ftc_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map common FTC/FRC header spellings onto checker signal names."""
    aliases = {
        "battery_v": "battery_voltage", "battery": "battery_voltage",
        "voltage_v": "voltage", "heading": "heading_deg",
        "gyro_heading": "heading_deg", "imu_heading": "heading_deg",
        "imu_yaw": "heading_deg", "yaw_deg": "heading_deg",
        "odometry_x": "x", "odometry_y": "y",
        "x_position": "x", "y_position": "y",
    }
    output: list[dict[str, Any]] = []
    for row in rows:
        normalized: dict[str, Any] = {}
        for original, value in row.items():
            key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(original))
            key = re.sub(r"[^a-zA-Z0-9]+", "_", key).strip("_").lower()
            key = aliases.get(key, key)
            if key.endswith("_encoder_ticks"):
                key = key[:-len("_encoder_ticks")] + "_encoder"
            if key == "motor_power":
                key = "power"
            normalized[key] = value
        output.append(normalized)
    return output


def validate_ftc_log(rows: list[dict[str, Any]],
                     limits: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate one FTC/FRC telemetry log.

    rows: one dict per sample, with a time column (seconds) plus any of:
          *_power, *_position / *_encoder (ticks), *_velocity (ticks/sec),
          battery_voltage (or voltage), *_heading_deg, x/y odometry pairs.
    limits: overrides for FTC_DEFAULT_LIMITS keys.
    """
    rows = normalize_ftc_rows(rows)
    cfg = dict(FTC_DEFAULT_LIMITS)
    if limits:
        cfg.update(limits)
    power_lo, power_hi = cfg["motor_power"]
    volt_lo, volt_hi = cfg["battery_voltage"]

    failed: dict[str, list[str]] = {}
    warnings: dict[str, list[str]] = {}
    excluded: dict[int, list[str]] = {}

    def fail(check: str, row_idx: int, detail: str, reason: str) -> None:
        failed.setdefault(check, []).append(detail)
        excluded.setdefault(row_idx, []).append(reason)

    if not rows:
        return {
            "verdict": "failed",
            "failed_checks": [{
                "name": "no_data",
                "detail": "No rows provided — nothing to validate.",
            }],
            "warnings": [],
            "excluded_rows": {},
            "episodes": [],
            "summary": {"rows": 0},
        }

    def find_any(candidates) -> str | None:
        # Scan every row, not just the first: real logs sometimes have a
        # header/partial first row that is missing a column.
        for row in rows:
            found = _find_key(row, candidates)
            if found:
                return found
        return None

    time_key = find_any(TIME_KEYS) or "time"
    episode_key = find_any(EPISODE_KEYS)

    columns = sorted({k for row in rows for k in row})
    power_cols = [c for c in columns if c.endswith("_power") or c == "power"]
    heading_cols = [c for c in columns
                    if c == "heading_deg" or c.endswith("_heading_deg")]
    voltage_col = next((c for c in columns if "battery" in c or c == "voltage"), None)
    numeric_signal_cols = set(power_cols + heading_cols)
    numeric_signal_cols.update(
        col for col in columns
        if col.endswith(("_position", "_encoder", "_velocity")) or col in {"x", "y"}
    )
    if voltage_col:
        numeric_signal_cols.add(voltage_col)
    if time_key in columns:
        numeric_signal_cols.add(time_key)

    has_valid_time = any(_num(row.get(time_key)) is not None for row in rows)
    if not has_valid_time:
        warnings.setdefault("time_coverage", []).append(
            "No numeric timestamp was found; encoder, heading, battery-sag, "
            "and odometry step checks could not run."
        )

    has_supported_signal = bool(
        power_cols
        or voltage_col
        or heading_cols
        or any(c.endswith("_position") or c.endswith("_encoder") for c in columns)
        or "x" in columns
        or any(c.endswith("_x") for c in columns)
    )
    if not has_supported_signal:
        failed.setdefault("no_robot_signals", []).append(
            "No supported FTC/FRC telemetry signals were found in the recording."
        )

    # --- per-row range checks -------------------------------------------
    for idx, row in enumerate(rows):
        for col in sorted(numeric_signal_cols):
            if col not in row:
                fail(
                    "invalid_numeric_signal",
                    idx,
                    f"row {idx}: {col} is missing",
                    f"{col} is missing or non-finite/non-numeric",
                )
                continue
            raw = row[col]
            value = _num(raw)
            if raw is None or value is None:
                fail(
                    "invalid_numeric_signal",
                    idx,
                    f"row {idx}: {col} must contain a finite numeric value; got {raw!r}",
                    f"{col} is missing or non-finite/non-numeric",
                )
        for col in power_cols:
            v = _num(row.get(col))
            if v is not None and not (power_lo <= v <= power_hi):
                fail("power_range", idx,
                     f"row {idx}: {col}={v:g} outside [{power_lo:g}, {power_hi:g}]",
                     f"{col}={v:g} outside [{power_lo:g}, {power_hi:g}]")
        if voltage_col:
            v = _num(row.get(voltage_col))
            if v is not None and not (volt_lo <= v <= volt_hi):
                warnings.setdefault("battery_voltage_range", []).append(
                    f"row {idx}: {voltage_col}={v:g} outside warn band "
                    f"[{volt_lo:g}, {volt_hi:g}]")

    # --- consecutive-step checks (never across episode boundaries) ------
    def group_of(row: dict[str, Any]) -> str:
        return str(row.get(episode_key, "log")) if episode_key else "log"

    for idx in range(1, len(rows)):
        prev, row = rows[idx - 1], rows[idx]
        if group_of(prev) != group_of(row):
            continue
        t0, t1 = _num(prev.get(time_key)), _num(row.get(time_key))
        if t0 is None or t1 is None:
            continue
        dt = t1 - t0
        if dt <= 0:
            fail("time_order", idx,
                 f"row {idx}: time did not increase ({t0:g} -> {t1:g})",
                 "time did not increase")
            continue

        total_power = sum(abs(_num(row.get(c)) or 0.0) for c in power_cols)

        # battery sag: voltage low AND motors working hard, same moment
        if voltage_col:
            v = _num(row.get(voltage_col))
            if (v is not None and v < cfg["battery_sag_voltage"]
                    and total_power >= cfg["sag_min_total_power"]):
                fail("battery_sag", idx,
                     f"row {idx}: battery {v:g}V below {cfg['battery_sag_voltage']:g}V "
                     f"while total |power| is {total_power:g}",
                     f"battery sag: {v:g}V under load {total_power:g}")

        # encoder checks: position column -> implied velocity
        for col in columns:
            if not (col.endswith("_position") or col.endswith("_encoder")):
                continue
            p0, p1 = _num(prev.get(col)), _num(row.get(col))
            if p0 is None or p1 is None:
                continue
            derived = (p1 - p0) / dt
            vel_col = col[: -len("position")] + "velocity" if col.endswith("_position") else None
            reported = _num(row.get(vel_col)) if vel_col else None
            if reported is not None and abs(derived - reported) > cfg["velocity_tolerance"]:
                fail("encoder_velocity", idx,
                     f"row {idx}: {col} implies {derived:g}/s but "
                     f"{vel_col} says {reported:g}/s",
                     f"encoder-derived velocity {derived:g}/s disagrees with "
                     f"reported {reported:g}/s")
            if (abs(derived) > cfg["min_moving_speed"] and power_cols
                    and all(abs(_num(row.get(c)) or 0.0) < 0.05 for c in power_cols)):
                fail("motion_without_power", idx,
                     f"row {idx}: {col} moving at {derived:g}/s with motor power ~0",
                     f"{col} moved at {derived:g}/s with no motor power")

        # heading: unwrap first (+179 -> -179 is a 2-degree turn, not a jump)
        for col in heading_cols:
            h0, h1 = _num(prev.get(col)), _num(row.get(col))
            if h0 is None or h1 is None:
                continue
            step = ((h1 - h0 + 180.0) % 360.0) - 180.0
            if abs(step) > cfg["heading_jump_deg"]:
                fail("heading_jump", idx,
                     f"row {idx}: {col} jumped {step:g} degrees in one step "
                     f"({h0:g} -> {h1:g})",
                     f"{col} jumped {step:g} deg in one step")

        # odometry: x/y pairs imply a ground speed
        for col in columns:
            if col == "x":
                pair = ("x", "y")
            elif col.endswith("_x"):
                pair = (col, col[:-2] + "_y")
            else:
                continue
            x0, y0 = _num(prev.get(pair[0])), _num(prev.get(pair[1]))
            x1, y1 = _num(row.get(pair[0])), _num(row.get(pair[1]))
            if None in (x0, y0, x1, y1):
                continue
            speed = math.hypot(x1 - x0, y1 - y0) / dt
            if speed > cfg["max_speed"]:
                fail("odometry_jump", idx,
                     f"row {idx}: odometry implies speed {speed:g}/s, "
                     f"above max {cfg['max_speed']:g}/s",
                     f"odometry speed {speed:g}/s above max {cfg['max_speed']:g}/s")

    # --- episode summary ---------------------------------------------------
    episodes: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(rows):
        name = group_of(row)
        ep = episodes.setdefault(name, {"episode_id": name, "samples": 0,
                                        "flagged_samples": 0})
        ep["samples"] += 1
        if idx in excluded:
            ep["flagged_samples"] += 1

    return {
        "verdict": "failed" if failed else "warning" if warnings else "passed",
        "failed_checks": [
            {"name": name, "detail": "; ".join(details[:5])}
            for name, details in sorted(failed.items())
        ],
        "warnings": [
            {"name": name, "detail": "; ".join(details[:5])}
            for name, details in sorted(warnings.items())
        ],
        "excluded_rows": {str(i): reasons for i, reasons in sorted(excluded.items())},
        "episodes": list(episodes.values()),
        "summary": {
            "rows": len(rows),
            "flagged_rows": len(excluded),
            "median_dt_seconds": _median_dt(rows, time_key),
        },
    }
