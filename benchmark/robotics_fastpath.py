#!/usr/bin/env python3
"""Compare the hosted robotics validation latency with a committed baseline.

Run from the repository root:
  python benchmark/robotics_fastpath.py --before-ref 7a9d5c3

The baseline is extracted with ``git archive`` into a temporary directory, so
this does not switch or stash the user's working branch.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

ROWS = 400
WARMUPS = 4
REPETITIONS = 15


def _payload() -> dict:
    return {
        "data": [
            {
                "episode_id": "benchmark",
                "time": index * 0.01,
                "joint_1_position": 0.4 * __import__("math").sin(index * 0.01),
                "joint_1_velocity": 0.4 * __import__("math").cos(index * 0.01),
            }
            for index in range(ROWS)
        ],
        "simulation_type": "robotics",
        "run_ai": False,
    }


def _measure() -> float:
    import logging

    sys.path.insert(0, str(Path.cwd()))
    logging.getLogger("simapi").setLevel(logging.WARNING)
    from starlette.testclient import TestClient
    from api import server

    server.app.dependency_overrides[server.caller_identity] = lambda: "robotics-fastpath-benchmark"
    payload = _payload()
    with TestClient(server.app) as client:
        for _ in range(WARMUPS):
            response = client.post("/v1/validate/physics-only", json=payload)
            response.raise_for_status()
        samples = []
        for _ in range(REPETITIONS):
            started = time.perf_counter()
            response = client.post("/v1/validate/physics-only", json=payload)
            response.raise_for_status()
            samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(samples)


def _baseline_median(ref: str, root: Path) -> float:
    with tempfile.TemporaryDirectory(prefix="simapi-fastpath-before-") as directory:
        archive_process = subprocess.Popen(
            ["git", "archive", ref], cwd=root, stdout=subprocess.PIPE
        )
        assert archive_process.stdout is not None
        with tarfile.open(fileobj=archive_process.stdout, mode="r|") as archive:
            archive.extractall(directory, filter="data")
        if archive_process.wait() != 0:
            raise RuntimeError(f"Could not archive baseline revision {ref!r}")

        env = os.environ.copy()
        env["PYTHONPATH"] = directory + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--measure-only"],
            cwd=directory,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return float(json.loads(result.stdout.strip().splitlines()[-1])["median_ms"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-ref", default="7a9d5c3")
    parser.add_argument("--measure-only", action="store_true")
    args = parser.parse_args()
    if args.measure_only:
        print(json.dumps({"median_ms": _measure()}))
        return

    root = Path(__file__).resolve().parents[1]
    before = _baseline_median(args.before_ref, root)
    after = _measure()
    print(f"Payload: {ROWS} robotics rows; {WARMUPS} warmups; {REPETITIONS} timed requests")
    print(f"Before ({args.before_ref}): {before:.2f} ms median")
    print(f"After: {after:.2f} ms median")
    print(f"Speedup: {before / after:.2f}x")


if __name__ == "__main__":
    main()
