"""Convert declared robotics input units to the engine's canonical units.

Joint positions use radians, angular velocities use radians per second, and
torque/effort use newton metres. Limit values are canonical by default; an
optional ``limit_units`` mapping can declare non-canonical bound units.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_").replace(".", "_")


def _factor(signal: str, unit: str, *, is_prismatic: bool = False) -> float:
    unit = unit.strip().lower().replace(" ", "")
    if signal.endswith("_position"):
        supported = {"m": 1.0} if is_prismatic else {"rad": 1.0, "deg": math.pi / 180.0}
    elif signal.endswith("_velocity"):
        supported = {"m/s": 1.0} if is_prismatic else {"rad/s": 1.0, "deg/s": math.pi / 180.0}
    elif signal.endswith(("_torque", "_effort")):
        supported = {"nm": 1.0}
    elif signal.endswith("_force"):
        supported = {"n": 1.0}
    else:
        raise ValueError(
            f"Units can only be declared for joint position, velocity, torque, or effort signals; got '{signal}'."
        )
    try:
        return supported[unit]
    except KeyError as exc:
        choices = ", ".join(supported)
        raise ValueError(f"Unsupported unit '{unit}' for '{signal}'. Supported units: {choices}.") from exc


def _multiply(value: Any, factor: float) -> Any:
    if factor == 1.0:
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return number * factor if math.isfinite(number) else value


def convert_robotics_inputs(
    data: pd.DataFrame,
    source_rows: list[dict[str, Any]],
    units: dict[str, str] | None = None,
    limits: dict[str, tuple[float, float]] | None = None,
    limit_units: dict[str, str] | None = None,
    *,
    prismatic_signals: set[str] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, tuple[float, float]], dict[str, str]]:
    """Return converted input copies and conversion metadata.

    ``units`` describes values in the submitted data. Robot limit bounds are
    already canonical radians / radians per second / Nm unless a caller
    explicitly supplies ``limit_units``. A unit declaration must name a signal
    that is actually present in the data.
    """
    unit_map = units or {}
    limit_unit_map = limit_units or {}
    columns = {_normalize(str(column)): column for column in data.columns}
    converted_data = data.copy()
    converted_rows = [dict(row) for row in source_rows]
    converted_limits = dict(limits or {})
    conversions: dict[str, str] = {}
    linear_signals = {_normalize(signal) for signal in (prismatic_signals or set())}

    for declared_signal, unit in unit_map.items():
        normalized = _normalize(str(declared_signal))
        column = columns.get(normalized)
        if column is None:
            raise ValueError(f"Units were declared for signal '{declared_signal}', but that signal is not in the data.")
        is_prismatic = normalized in linear_signals
        factor = _factor(normalized, str(unit), is_prismatic=is_prismatic)
        if factor != 1.0:
            converted_data[column] = pd.to_numeric(converted_data[column], errors="coerce") * factor
            for row in converted_rows:
                for key in row:
                    if _normalize(str(key)) == normalized:
                        row[key] = _multiply(row[key], factor)
            target = (
                "m" if normalized.endswith("_position") and is_prismatic else
                "rad" if normalized.endswith("_position") else
                "m/s" if normalized.endswith("_velocity") and is_prismatic else
                "rad/s" if normalized.endswith("_velocity") else
                "Nm"
            )
            conversions[normalized] = f"{str(unit).strip().lower()}->{target}"
        elif is_prismatic and str(unit).strip().lower() in {"m", "m/s"}:
            target = "m" if normalized.endswith("_position") else "m/s"
            conversions[normalized] = f"{str(unit).strip().lower()}->{target}"

    for declared_signal, unit in limit_unit_map.items():
        normalized = _normalize(str(declared_signal))
        if normalized not in columns:
            raise ValueError(f"Limit units were declared for signal '{declared_signal}', but that signal is not in the data.")
        factor = _factor(normalized, str(unit), is_prismatic=normalized in linear_signals)
        for limit_name, bound in list(converted_limits.items()):
            if _normalize(str(limit_name)) == normalized:
                converted_limits[limit_name] = (float(bound[0]) * factor, float(bound[1]) * factor)

    return converted_data, converted_rows, converted_limits, conversions
