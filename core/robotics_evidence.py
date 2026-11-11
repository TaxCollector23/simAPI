"""Compact per-sample evidence for manipulation checks and declared bounds."""
from __future__ import annotations

from typing import Any

from core.robotics_trajectory import normalize, number


def build_evidence(source: list[dict[str, Any]], checks: list[dict[str, Any]],
                   limits: dict[str, tuple[float, float]], conditions: dict[str, float],
                   summary: dict[str, Any]) -> dict[str, Any]:
    rows = [{normalize(k): v for k, v in row.items()} for row in source]
    time_key, group_key = summary["time_column"], summary["episode_column"]
    bounds = {normalize(k): v for k, v in limits.items()}
    evidence: list[dict[str, Any]] = []
    previous: dict[int, int | None] = {}
    last: dict[str, int] = {}
    total = 0

    def group(row: dict[str, Any]) -> str:
        return str(row.get(group_key, "(missing episode)")) if group_key else "Episode 1"

    def push(index: int, signal: str, check: str, observed: float | None,
             expected: tuple[float, float] | list[float] | None, detail: str,
             status: str = "failed") -> None:
        nonlocal total
        total += 1
        if len(evidence) < 1000:
            evidence.append({"check": check, "status": status, "signal": signal,
                             "episode_id": group(rows[index]), "sample_index": index,
                             "time": number(rows[index].get(time_key)) if time_key else None,
                             "observed": observed, "expected": list(expected) if expected else None,
                             "detail": detail})

    for index, row in enumerate(rows):
        episode = group(row)
        previous[index] = last.get(episode)
        last[episode] = index
    present = set().union(*(row.keys() for row in rows)) if rows else set()
    for signal, bound in bounds.items():
        if signal not in present and not any(c["name"] == f"robotics_limit:{signal}" and c["status"] == "failed" for c in checks):
            continue
        for index, row in enumerate(rows):
            value = number(row.get(signal))
            if value is None or value < bound[0] or value > bound[1]:
                push(index, signal, f"robotics_limit:{signal}", value, bound,
                     "Signal is missing or non-numeric." if value is None else "Outside the configured range.")
    for check in checks:
        if not check.get("indices") or check.get("status") not in {"failed", "warning"}:
            continue
        for index in check.get("indices", []):
            row, signal = rows[index], check["column"]
            prior = previous.get(index)
            left = rows[prior] if prior is not None else None
            observed = number(row.get(signal))
            expected: tuple[float, float] | list[float] | None = None
            name = check["name"]
            if name.startswith(("robotics_derived_limit:", "robotics_consistency:")):
                acceleration = signal.endswith("_acceleration")
                source_signal = signal.removesuffix("acceleration" if acceleration else "velocity") + ("velocity" if acceleration else "position")
                a, b = number(left.get(source_signal)) if left else None, number(row.get(source_signal))
                t0, t1 = number(left.get(time_key)) if left and time_key else None, number(row.get(time_key)) if time_key else None
                observed = (b - a) / (t1 - t0) if a is not None and b is not None and t0 is not None and t1 is not None and t1 > t0 else None
                expected = bounds.get(signal)
                if name.startswith("robotics_consistency:"):
                    a, b = number(left.get(signal)) if left else None, number(row.get(signal))
                    tolerance = conditions.get("acceleration_tolerance" if acceleration else "velocity_tolerance", 0)
                    expected = [(a+b)/2-tolerance, (a+b)/2+tolerance] if a is not None and b is not None else None
            elif name == "robotics_sample_gaps" and left and time_key:
                a, b = number(left.get(time_key)), number(row.get(time_key))
                observed = b-a if a is not None and b is not None else None
                expected = [0, conditions["max_time_step"]]
            else:
                low, high = check.get("low"), check.get("high")
                if low is not None and high is not None:
                    expected = [low, high]
            push(index, signal, name, observed, expected, check["detail"], check["status"])
    return {"entries": evidence, "total": total, "truncated": total > len(evidence)}
