"""Motion checks use independent signals and never cross episode boundaries."""
import json
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from core.robotics_trajectory import analyze_trajectories
from core.robotics_validation import check_robotics_limits

CASES = [
    {
        "name": "episode resets do not create a velocity spike",
        "rows": [
            {"episode_id": "a", "time": 0, "joint_1_position": 0, "joint_1_velocity": 1},
            {"episode_id": "a", "time": 0.1, "joint_1_position": 0.1, "joint_1_velocity": 1},
            {"episode_id": "b", "time": 0, "joint_1_position": 4, "joint_1_velocity": 1},
            {"episode_id": "b", "time": 0.1, "joint_1_position": 4.1, "joint_1_velocity": 1},
        ],
        "limits": {"joint_1_velocity": [-2, 2]},
        "conditions": {"velocity_tolerance": 0.01, "max_time_step": 0.2},
        "failed": [],
    },
    {
        "name": "position jump contradicts reported velocity",
        "rows": [
            {"time": 0, "joint_1_position": 0, "joint_1_velocity": 0},
            {"time": 0.1, "joint_1_position": 1, "joint_1_velocity": 0},
        ],
        "limits": {"joint_1_velocity": [-2, 2]},
        "conditions": {"velocity_tolerance": 0.1},
        "failed": ["robotics_derived_limit:joint_1_velocity", "robotics_consistency:joint_1_velocity"],
    },
    {
        "name": "velocity jump exceeds acceleration limit",
        "rows": [{"time": 0, "joint_2_velocity": 0}, {"time": 0.1, "joint_2_velocity": 4}],
        "limits": {"joint_2_acceleration": [-5, 5]}, "conditions": {},
        "failed": ["robotics_derived_limit:joint_2_acceleration"],
    },
    {
        "name": "dropped samples and duplicate time",
        "rows": [{"time": 0}, {"time": 1}, {"time": 1}, {"time": None}],
        "limits": {}, "conditions": {"max_time_step": 0.2},
        "failed": ["robotics_time_order", "robotics_sample_gaps"],
    },
    {
        "name": "missing time is explicitly not evaluated",
        "rows": [{"joint_1_position": 0}, {"joint_1_position": 1}],
        "limits": {}, "conditions": {"velocity_tolerance": 0.1}, "failed": [],
    },
]


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_motion_findings(case):
    report = analyze_trajectories(case["rows"], case["limits"], case["conditions"])
    assert [check["name"] for check in report["checks"] if check["status"] == "failed"] == case["failed"]
    if not any("time" in row for row in case["rows"]):
        assert report["checks"][0]["status"] == "warning"
        assert report["summary"]["episodes"][0]["duration_seconds"] is None


def test_python_and_hosted_motion_engines_agree():
    node = shutil.which("node")
    if not node or int(subprocess.check_output([node, "--version"], text=True).strip().split(".")[0][1:]) < 22:
        pytest.skip("Cross-runtime parity requires Node 22+ TypeScript stripping")
    root = Path(__file__).resolve().parents[1]
    script = """
      import { analyzeTrajectories } from './web/lib/robotics-trajectory.ts';
      let input = ''; for await (const chunk of process.stdin) input += chunk;
      const cases = JSON.parse(input);
      process.stdout.write(JSON.stringify(cases.map(c => analyzeTrajectories(c.rows, c.limits, c.conditions))));
    """
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        input=json.dumps(CASES), text=True, capture_output=True, cwd=root, check=True,
    )
    hosted = json.loads(result.stdout)
    for case, actual in zip(CASES, hosted, strict=True):
        expected = analyze_trajectories(case["rows"], case["limits"], case["conditions"])
        assert [(c["name"], c["status"], c["violations"]) for c in expected["checks"]] == [
            (c["name"], c["status"], c["violations"]) for c in actual["checks"]
        ]
        assert expected["summary"] == actual["summary"]


def test_configured_signal_missing_in_one_sample_fails_closed():
    rows = [{"joint_1_position": 0.1}, {"joint_1_position": None}, {"joint_1_position": float("inf")}]
    report = check_robotics_limits(pd.DataFrame(rows), {"joint_1_position": (-1, 1)}, source_rows=rows)
    assert set(report["excluded"]) == {1, 2}


def test_per_joint_defaults_apply_without_custom_profile():
    report = check_robotics_limits(pd.DataFrame([{"joint_7_torque": 1e8}]))
    assert report["checks"][0]["status"] == "failed"
