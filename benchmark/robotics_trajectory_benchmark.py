"""Compare the episode-aware trajectory analyzer with its pre-vectorization version.

Run from any directory with ``python benchmark/robotics_trajectory_benchmark.py``.
The old implementation is loaded from the repository revision that preceded
vectorization; set ``SIMAPI_TRAJECTORY_BASELINE`` to compare another revision.
"""
from __future__ import annotations

import math
import os
import statistics
import subprocess
import sys
import time
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.robotics_trajectory import analyze_trajectories as analyze_vectorized  # noqa: E402

BASELINE_REVISION = os.environ.get(
    "SIMAPI_TRAJECTORY_BASELINE", "7a9d5c39c64b32926006f46c69f3ea9f38998aeb"
)
DEFAULT_ROWS = 200_000
DEFAULT_JOINTS = 6
DEFAULT_REPETITIONS = 5


def load_baseline():
    source = subprocess.check_output(
        ["git", "-C", str(ROOT), "show", f"{BASELINE_REVISION}:core/robotics_trajectory.py"],
        text=True,
    )
    module = types.ModuleType("simapi_baseline_robotics_trajectory")
    exec(compile(source, f"{BASELINE_REVISION}:core/robotics_trajectory.py", "exec"), module.__dict__)
    return module.analyze_trajectories


def make_rows(row_count: int, joint_count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    episode_count = 4
    base, remainder = divmod(row_count, episode_count)
    frequencies = [0.2 + 0.1 * joint for joint in range(joint_count)]
    for episode in range(episode_count):
        count = base + (episode < remainder)
        for offset in range(count):
            timestamp = offset / 1_000
            row: dict[str, Any] = {"episode_id": f"episode-{episode}", "time": timestamp}
            for joint, frequency in enumerate(frequencies, start=1):
                phase = timestamp * frequency
                row[f"joint_{joint}_position"] = math.sin(phase)
                row[f"joint_{joint}_velocity"] = frequency * math.cos(phase)
            rows.append(row)
    return rows


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--joints", type=int, default=DEFAULT_JOINTS)
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    args = parser.parse_args()
    if args.rows < 1 or args.joints < 1 or args.repetitions < 1:
        parser.error("rows, joints, and repetitions must be positive")

    rows = make_rows(args.rows, args.joints)
    limits = {
        **{f"joint_{joint}_velocity": (-2.5, 2.5) for joint in range(1, args.joints + 1)},
        **{f"joint_{joint}_acceleration": (-2.5, 2.5) for joint in range(1, args.joints + 1)},
    }
    conditions = {
        "max_time_step": 0.002,
        "velocity_tolerance": 0.01,
        "acceleration_tolerance": 0.01,
    }
    analyze_baseline = load_baseline()

    reference_report = analyze_baseline(rows, limits, conditions)
    vectorized_report = analyze_vectorized(rows, limits, conditions)
    if reference_report != vectorized_report:
        raise AssertionError("Baseline and vectorized reports differ")

    baseline_durations: list[float] = []
    vectorized_durations: list[float] = []
    # Alternate order to reduce bias from system load or thermal drift.
    for repetition in range(args.repetitions):
        runs = (
            (analyze_baseline, baseline_durations),
            (analyze_vectorized, vectorized_durations),
        )
        if repetition % 2:
            runs = tuple(reversed(runs))
        for analyze, samples in runs:
            start = time.perf_counter()
            report = analyze(rows, limits, conditions)
            samples.append(time.perf_counter() - start)
            if report != reference_report:
                raise AssertionError("Analyzer output changed between benchmark repetitions")

    baseline_median = statistics.median(baseline_durations)
    vectorized_median = statistics.median(vectorized_durations)
    print(f"rows: {args.rows:,}; joints: {args.joints}; episodes: 4")
    print(f"baseline revision: {BASELINE_REVISION}")
    print(f"repetitions: {args.repetitions}; checks: {len(reference_report['checks'])}")
    print(f"baseline median: {baseline_median:.3f} s")
    print(f"vectorized median: {vectorized_median:.3f} s")
    print(f"speedup: {baseline_median / vectorized_median:.2f}x")


if __name__ == "__main__":
    main()
