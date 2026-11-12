"""Acceptance regressions for the eight requested corrections."""
import json
import math
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from core.physics_validator import PhysicsValidator, SimulationType
from core.suggest_limits import suggest_and_validate, suggest_limits
from integrations.robotics_validation import load_limits_profile


def clean_torque():
    return [{"episode_id": ep, "t": i * .1, "joint_1_torque": -20 if i < 50 else 55}
            for ep in range(3) for i in range(100)]


def test_percentiles_margin_spike_and_self_validation():
    rows = clean_torque()
    clean = suggest_limits(rows)
    spike = suggest_limits(rows + [{"joint_1_torque": 5000}])
    assert clean["robotics_limits"]["joint_1_torque"] == [-38.75, 73.75]
    assert spike["robotics_limits"] == clean["robotics_limits"]
    assert "1 contamination" in spike["warnings"][0]
    assert suggest_and_validate(rows, rows)["validation"]["excluded_rows"] == 0
    symmetric = [{"joint_1_torque": -55 if i < 50 else 55} for i in range(100)]
    assert suggest_limits(symmetric)["robotics_limits"]["joint_1_torque"] == [-82.5, 82.5]


@pytest.mark.parametrize("margin", [0, .9, -1, float('nan'), float('inf'), True, "bad"])
def test_bad_margin_is_named(margin):
    with pytest.raises(ValueError, match="margin"):
        suggest_limits(clean_torque(), margin)


def test_empty_frozen_and_caps():
    with pytest.raises(ValueError):
        suggest_limits([])
    frozen = suggest_limits([{"joint_1_position": 1}] * 10)
    assert frozen["robotics_limits"] == {}
    assert "frozen" in frozen["warnings"][0]
    with pytest.raises(ValueError):
        suggest_and_validate([{"joint_1_position": 1}], [{"joint_1_position": 2}])
    for signal, cap in [("torque", 150), ("velocity", 3), ("acceleration", 25), ("position", 2*math.pi)]:
        result = suggest_limits([{f"joint_1_{signal}": v} for v in np.linspace(-cap, cap, 100)])
        assert result["robotics_limits"][f"joint_1_{signal}"] == [-cap, cap]


def test_observed_inliers_are_covered():
    values = list(np.linspace(-20, 55, 300)) + [-30, 65]
    low, high = suggest_limits([{"joint_1_torque": v} for v in values], margin=1)["robotics_limits"]["joint_1_torque"]
    assert low <= min(values) and high >= max(values)


def teleport_rows():
    return [{"t": i*.1, "joint_1_position": i*.05 if i < 4 else 1+(i-4)*.05,
             "joint_1_velocity": .5, "joint_1_torque": 10} for i in range(8)]


def test_learned_limits_exclude_teleport():
    clean = [{"t": i*.1, "joint_1_position": i*.05} for i in range(8)]
    assert suggest_and_validate(clean, teleport_rows())["validation"]["excluded_rows"] > 0
    assert suggest_and_validate(clean, clean)["validation"]["excluded_rows"] == 0


def test_api_top_level_excluded_indices(client):
    response = client.post('/v1/validate/physics-only', json={
        'data': teleport_rows(), 'simulation_type': 'robotics',
        'robotics_limits': {'joint_1_torque': [-70,70], 'joint_1_velocity': [-2,2]},
    })
    assert response.status_code == 200
    assert response.json()['excluded_indices'] == [4]


@pytest.mark.parametrize('contents', [b'', b'\xff\xfe\x80', b'garbage\x00bytes,noise\nhello,world\n',
                                      b'torque\n', b'foo,bar\n,\n', b'time\n0\n'])
def test_bad_upload_fails_closed_with_request_id(client, contents):
    response = client.post('/v1/validate/upload', files={'file': ('run.csv', contents, 'text/csv')})
    assert response.status_code == 400
    request_id = response.json()['error']['request_id']
    assert request_id and request_id == response.headers['X-Request-ID']


def test_tightened_legacy_physics_bounds():
    report = PhysicsValidator().validate(pd.DataFrame({'joint_acceleration': [51.], 'end_effector_force': [1001.]}), SimulationType.ROBOTICS, {}, 'bounds')
    assert report.exclusions


def test_profiles_reject_bad_ranges(tmp_path):
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps({'robotics_limits': {'joint_1_torque': [70, -70]}}))
    with pytest.raises(ValueError, match='profile'):
        load_limits_profile(path)


def test_lerobot_profile_real_parquet_exit_one(tmp_path):
    pytest.importorskip('pyarrow')
    dataset = tmp_path / 'teleport.parquet'
    rows = teleport_rows()
    pd.DataFrame({'episode_index': [0]*len(rows), 'timestamp': [r['t'] for r in rows],
                  'observation.state': [[r['joint_1_position']] for r in rows],
                  'joint_1_torque': [10.]*len(rows)}).to_parquet(dataset)
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'robotics_limits': {'joint_1_torque': [-70,70], 'joint_1_velocity': [-2,2]}}))
    result = subprocess.run([sys.executable, '-m', 'integrations.lerobot_loader', str(dataset), '--profile', str(profile)], capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'failed'
    assert any(c['name'] == 'robotics_limit:joint_1_torque' and c['status'] == 'passed' for c in report['checks'])
    assert any(c['name'] == 'robotics_derived_limit:joint_1_velocity' and c['status'] == 'failed' for c in report['checks'])
