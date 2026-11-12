from api.config import Settings


def test_default_trajectory_screening(client):
    for jump, status, indices in [(True, 'failed', [4]), (False, 'warning', [])]:
        rows = [{'t': i*.02, 'joint_1_position': 1.2 if jump and i==4 else i*.02,
                 'joint_1_torque': 95 if i==4 else 10} for i in range(5)]
        response = client.post('/v1/validate/physics-only', json={'data': rows, 'simulation_type': 'robotics'})
        assert response.json()['status'] == status
        assert response.json()['excluded_indices'] == indices


def test_default_row_cap(client, monkeypatch):
    assert Settings().max_rows == 10000
    response = client.post('/v1/validate', json={'data': [{'joint_1_torque': 1}]*10001, 'simulation_type': 'robotics'})
    assert response.status_code == 413
    assert response.json()['error']['details']['limit'] == 10000
