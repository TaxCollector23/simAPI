"""End-to-end API contract tests."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_api_test_rate_limit():
    from api import server

    previous = server.app.dependency_overrides.get(server.caller_identity)
    server.app.dependency_overrides[server.caller_identity] = lambda: "api-contract-tests"
    yield
    if previous is None:
        server.app.dependency_overrides.pop(server.caller_identity, None)
    else:
        server.app.dependency_overrides[server.caller_identity] = previous


def test_health_ok(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["domains"] == 21
    assert "ai_enabled" in body


def test_metrics_exposes_prometheus_text(client):
    client.get("/v1/health")  # generate at least one request
    r = client.get("/v1/metrics")
    assert r.status_code == 200
    assert "simapi_http_requests_total" in r.text
    assert "simapi_uptime_seconds" in r.text


def test_validate_physics_only(client, sample_payload):
    r = client.post("/v1/validate/physics-only", json=sample_payload)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("passed", "warning", "failed")
    assert body["all_checks"] > 0
    assert body["ai_status"] == "disabled"  # AI skipped for physics-only
    # Canonical field and back-compat alias must agree.
    assert body["issues"] == body["physics_checks"]


def test_robotics_torque_bounds_cannot_be_training_ready(client):
    data = [{"joint_torque": 250_000 + i} for i in range(20)]
    response = client.post("/v1/validate/physics-only", json={
        "data": data,
        "simulation_type": "robotics",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["training_ready"] is False
    assert body["trials_excluded"] == 20
    assert any(issue["name"] == "robotics_limit:joint_torque" for issue in body["issues"])


def test_robotics_model_limits_are_applied_per_joint(client):
    data = [{"joint_1_position": i / 10} for i in range(10)]
    response = client.post("/v1/validate/physics-only", json={
        "data": data,
        "simulation_type": "robotics",
        "robotics_limits": {"joint_1_position": [-0.25, 0.25]},
    })

    assert response.status_code == 200
    body = response.json()
    assert body["training_ready"] is False
    assert body["trials_excluded"] == 7
    check = next(check for check in body["robotics_checks"] if check["column"] == "joint_1_position")
    assert check["status"] == "failed"
    assert check["violations"] == 7


def test_robotics_time_order_resets_at_episode_boundary(client):
    data = [
        {"episode_id": "a", "time": 0.0, "joint_1_position": 0.0},
        {"episode_id": "a", "time": 0.1, "joint_1_position": 0.1},
        {"episode_id": "a", "time": 0.05, "joint_1_position": 0.2},
        {"episode_id": "b", "time": 0.0, "joint_1_position": 0.3},
    ]
    response = client.post("/v1/validate/physics-only", json={
        "data": data,
        "simulation_type": "robotics",
    })

    assert response.status_code == 200
    body = response.json()
    check = next(check for check in body["robotics_checks"] if check["name"] == "robotics_time_order")
    assert check["status"] == "failed"
    assert check["violations"] == 1
    assert body["training_ready"] is False
    assert any(item["trial_index"] == 2 for item in body["exclusions"])


def test_request_id_header_is_returned(client, sample_payload):
    r = client.post("/v1/validate/physics-only", json=sample_payload)
    assert r.headers.get("X-Request-ID")


def test_robotics_trajectory_findings_control_api_verdict(client):
    response = client.post("/v1/validate/physics-only", json={
        "data": [{"time": 0, "joint_1_position": 0, "joint_1_velocity": 0},
                 {"time": 0.1, "joint_1_position": 1, "joint_1_velocity": 0}],
        "simulation_type": "robotics", "robotics_limits": {"joint_1_velocity": [-2, 2]},
        "conditions": {"velocity_tolerance": 0.1},
    })
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["training_ready"] is False
    assert any(check["name"] == "robotics_derived_limit:joint_1_velocity" for check in body["robotics_checks"])
    assert body["robotics_summary"]["engine_version"] == "manipulation-2"
    assert body["robotics_summary"]["episodes"][0]["flagged_samples"] == 1


def test_robotics_invalid_check_options_are_rejected(client):
    response = client.post("/v1/validate/physics-only", json={
        "data": [{"time": 0}], "simulation_type": "robotics", "conditions": {"max_time_step": -1},
    })
    assert response.status_code == 422


def test_request_id_is_echoed_when_supplied(client):
    r = client.get("/v1/health", headers={"X-Request-ID": "trace-123"})
    assert r.headers["X-Request-ID"] == "trace-123"


def test_error_envelope_on_not_found(client):
    r = client.get("/v1/job/does-not-exist")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "not_found"
    assert "request_id" in err


def test_error_envelope_on_schema_violation(client):
    r = client.post("/v1/validate", json={"data": "not-a-list"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_failed"


def test_payload_too_large_is_rejected(client, monkeypatch):
    import dataclasses

    from api import server as srv

    monkeypatch.setattr(srv, "settings", dataclasses.replace(srv.settings, max_rows=5))
    payload = {"data": [{"cd": 0.3} for _ in range(10)], "simulation_type": "aerodynamics"}
    r = client.post("/v1/validate", json=payload)
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


def test_jobs_pagination(client, sample_payload):
    client.post("/v1/validate/physics-only", json=sample_payload)
    r = client.get("/v1/jobs?limit=1&offset=0")
    assert r.status_code == 200
    page = r.json()["pagination"]
    assert set(page) == {"total", "limit", "offset", "returned"}
    assert page["limit"] == 1


def test_job_ai_poll_exposes_exclusion_fields(client, sample_payload):
    """Regression test: the AI worker folds new exclusions into the job, but the
    poll endpoint used to only return `ai` — silently dropping any trial the AI
    orchestrator excluded that the physics engine had passed."""
    job_id = client.post("/v1/validate/physics-only", json=sample_payload).json()["job_id"]
    r = client.get(f"/v1/job/{job_id}/ai")
    assert r.status_code == 200
    body = r.json()
    for key in ("ai_exclusions", "exclusions", "trials_excluded", "trials_valid", "exclusion_rate", "status", "training_ready"):
        assert key in body


def test_demo_runs(client):
    r = client.post("/v1/demo")
    assert r.status_code == 200
    body = r.json()
    # The demo is pristine synthetic aerodynamics data — meant to show a
    # near-100% pass rate so first-time playground users get a positive result.
    # With more columns (each an independent chance at a rare >3.5-sigma
    # outlier in 500 samples), a handful of natural-noise exclusions is
    # expected and still a >98% pass rate.
    assert body["trials_submitted"] == 500
    assert body["trials_excluded"] <= 12


def test_unsupported_simulation_type_upload(client):
    r = client.post(
        "/v1/validate/upload",
        files={"file": ("d.csv", "cd,cl\n0.3,0.8\n0.31,0.82\n", "text/csv")},
        data={"simulation_type": "warp_drive"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unsupported_format"


def test_repair_preview_finds_duplicate_ids(client):
    r = client.post(
        "/v1/repair",
        json={"data": [{"trial_id": 1, "velocity": 150}, {"trial_id": 1, "velocity": 151}], "apply": False},
    )
    assert r.status_code == 200
    body = r.json()
    kinds = [p["kind"] for p in body["proposals"]]
    assert "duplicate_or_missing_ids" in kinds
    assert "repaired_data" not in body  # preview mode must not include the repaired dataset


def test_repair_apply_returns_repaired_data(client):
    r = client.post(
        "/v1/repair",
        json={"data": [{"trial_id": 1, "velocity": 150}, {"trial_id": 1, "velocity": 151}], "apply": True},
    )
    assert r.status_code == 200
    body = r.json()
    repaired_ids = [row["trial_id"] for row in body["repaired_data"]]
    assert len(set(repaired_ids)) == len(repaired_ids)  # IDs are unique after repair


def test_repair_on_clean_data_has_no_proposals(client):
    r = client.post(
        "/v1/repair",
        json={"data": [{"velocity": 150}, {"velocity": 151}, {"velocity": 152}]},
    )
    assert r.status_code == 200
    assert r.json()["proposals"] == []


def test_repair_handles_empty_data_gracefully(client):
    r = client.post("/v1/repair", json={"data": []})
    assert r.status_code == 200
    assert r.json()["proposals"] == []


def test_validate_dimensional_endpoint(client, sample_payload):
    r = client.post("/v1/validate/dimensional", json=sample_payload)
    assert r.status_code == 200
    body = r.json()
    assert body["n_rows"] == 30
    assert "impossible" in body and "inconsistent" in body and "unsuitable_for_training" in body
    assert isinstance(body["laws_discovered"], list)
    assert isinstance(body["units_resolved"], dict)
    # Ingestion normalizes cd/cl/re/ma to their canonical names before the
    # dimensional engine sees them; all four should resolve as dimensionless.
    for col in ("drag_coefficient", "lift_coefficient", "reynolds_number", "mach_number"):
        assert body["units_resolved"][col]["usable"], body["units_resolved"]


def test_validate_dimensional_catches_unit_swap(client):
    import numpy as np
    rng = np.random.default_rng(0)
    n = 60
    T = 293.15 + rng.normal(0, 1, n)
    rho = 1.225 + rng.normal(0, 0.006, n)
    P = rho * 287.05 * T
    P[5] = P[5] / 1000.0  # Pa written as kPa
    data = [{"temperature": float(t), "density": float(r), "pressure": float(p)}
            for t, r, p in zip(T, rho, P, strict=True)]
    r = client.post("/v1/validate/dimensional", json={"data": data, "simulation_type": "aerodynamics"})
    assert r.status_code == 200
    body = r.json()
    assert 5 in body["impossible"]


def test_robotics_fast_path_skips_general_engine_by_default(client, monkeypatch):
    import api.server as server

    def should_not_run(*args, **kwargs):
        raise AssertionError("dimensional engine should be opt-in for robotics")

    monkeypatch.setattr(server, "dimensional_validate", should_not_run)
    data = [
        {"episode_id": "run-a", "time": 0.0, "joint_1_position": 0.0},
        {"episode_id": "run-a", "time": 0.1, "joint_1_position": 0.1},
        {"episode_id": "run-b", "time": 0.0, "joint_1_position": 0.2},
        {"episode_id": "run-b", "time": 0.1, "joint_1_position": 0.3},
    ]
    response = client.post("/v1/validate/physics-only", json={
        "data": data,
        "simulation_type": "robotics",
        "robotics_limits": {"joint_1_position": [-1.0, 1.0]},
    })

    assert response.status_code == 200
    body = response.json()
    direct = server.ROBOTICS_ENGINE.validate(
        __import__("pandas").DataFrame(data),
        {"joint_1_position": (-1.0, 1.0)},
        source_rows=data,
    )
    assert body["robotics_checks"] == direct["checks"]
    assert {item["trial_index"] for item in body["exclusions"]} == set(direct["excluded"])
    assert body["legacy_physics"]["comparison_only"] is True
    assert len(body["episode_quality"]["episodes"]) == 2
    from core.physical_ai import episode_quality
    expected_quality = episode_quality(
        data, robotics_limits={"joint_1_position": (-1.0, 1.0)}
    )
    assert body["episode_quality"] == expected_quality


def test_robotics_episode_quality_uses_fixed_failure_labels(client):
    from core.physical_ai import FAILURE_LABELS, episode_quality

    data = [
        {"episode_id": "clean", "time": 0.0, "joint_1_position": 0.0},
        {"episode_id": "clean", "time": 0.1, "joint_1_position": 0.1},
        {"episode_id": "bad", "time": 0.0, "joint_1_position": 0.0},
        {"episode_id": "bad", "time": 0.1, "joint_1_position": 0.8},
    ]
    limits = {"joint_1_position": [-0.5, 0.5]}
    response = client.post("/v1/validate/physics-only", json={
        "data": data,
        "simulation_type": "robotics",
        "robotics_limits": limits,
    })
    expected = episode_quality(data, robotics_limits={"joint_1_position": (-0.5, 0.5)})

    assert response.status_code == 200
    quality = response.json()["episode_quality"]
    assert quality == expected
    bad_episode = next(item for item in quality["episodes"] if item["episode_id"] == "bad")
    assert bad_episode["failure_labels"] == ["limit_violation"]
    assert set(bad_episode["failure_labels"]).issubset(FAILURE_LABELS)


def test_robotics_episode_quality_is_returned_for_a_single_episode(client):
    response = client.post("/v1/validate/physics-only", json={
        "data": [
            {"episode_id": "one", "time": 0.0, "joint_1_position": 0.0},
            {"episode_id": "one", "time": 0.1, "joint_1_position": 0.1},
        ],
        "simulation_type": "robotics",
        "robotics_limits": {"joint_1_position": [-1.0, 1.0]},
    })

    assert response.status_code == 200
    episodes = response.json()["episode_quality"]["episodes"]
    assert len(episodes) == 1
    assert episodes[0]["episode_id"] == "one"
    assert episodes[0]["training_ready"] is True


def test_generic_robotics_validation_rejects_empty_rows(client):
    response = client.post("/v1/validate/physics-only", json={
        "data": [],
        "simulation_type": "robotics",
    })
    assert response.status_code == 400
    assert "at least one sample" in response.json()["error"]["message"]


def test_ftc_profile_api_dispatch_and_fail_closed_empty_logs(client):
    passing = client.post("/v1/validate/physics-only", json={
        "data": [
            {"time": 0.0, "left_motor_power": 0.2},
            {"time": 0.02, "left_motor_power": 0.3},
        ],
        "simulation_type": "robotics",
        "robotics_profile": "ftc",
    })
    failing = client.post("/v1/validate/physics-only", json={
        "data": [{"time": 0.0, "left_motor_power": 1.4}],
        "simulation_type": "robotics",
        "robotics_profile": "ftc",
    })
    empty = client.post("/v1/validate/physics-only", json={
        "data": [],
        "simulation_type": "robotics",
        "robotics_profile": "ftc",
    })
    unrecognized = client.post("/v1/validate/physics-only", json={
        "data": [{"time": 0.0, "comment": "no robot signals"}],
        "simulation_type": "robotics",
        "robotics_profile": "frc",
    })
    malformed = client.post("/v1/validate/physics-only", json={
        "data": [{"time": 0.0, "left_motor_power": "not-a-number"}],
        "simulation_type": "robotics",
        "robotics_profile": "ftc",
    })
    missing_signal = client.post("/v1/validate/physics-only", json={
        "data": [
            {"time": 0.0, "left_motor_power": 0.5},
            {"time": 0.02},
        ],
        "simulation_type": "robotics",
        "robotics_profile": "ftc",
    })

    assert [r.status_code for r in (passing, failing, empty, unrecognized, malformed, missing_signal)] == [
        200, 200, 200, 200, 200, 200
    ]
    assert passing.json()["status"] in {"passed", "warning"}
    assert passing.json()["profile"] == "ftc"
    assert failing.json()["status"] == "failed"
    assert failing.json()["training_ready"] is False
    assert empty.json()["status"] == "failed"
    assert empty.json()["ftc_frc_report"]["failed_checks"][0]["name"] == "no_data"
    assert unrecognized.json()["status"] == "failed"
    assert unrecognized.json()["ftc_frc_report"]["failed_checks"][0]["name"] == "no_robot_signals"
    assert malformed.json()["status"] == "failed"
    assert malformed.json()["training_ready"] is False
    assert malformed.json()["ftc_frc_report"]["failed_checks"][0]["name"] == "invalid_numeric_signal"
    assert missing_signal.json()["status"] == "failed"
    assert missing_signal.json()["ftc_frc_report"]["failed_checks"][0]["name"] == "invalid_numeric_signal"


_SIMPLE_URDF = """<robot name="one_joint">
  <link name="base"/><link name="tool"/>
  <joint name="joint_1" type="revolute"><parent link="base"/><child link="tool"/>
    <origin xyz="1 0 0"/><axis xyz="0 0 1"/>
  </joint>
</robot>"""


def test_urdf_kinematics_api_verdict_and_episode_export_quality(client):
    limits = {"joint_1_position": [-3.14, 3.14]}
    passing = client.post("/v1/validate/physics-only", json={
        "data": [{
            "episode_id": "aligned", "time": 0.0, "joint_1_position": 0.0,
            "end_effector_x": 1.0, "end_effector_y": 0.0, "end_effector_z": 0.0,
        }],
        "simulation_type": "robotics",
        "robotics_limits": limits,
        "urdf_xml": _SIMPLE_URDF,
        "run_ai": False,
    })
    mismatched = client.post("/v1/validate/physics-only", json={
        "data": [{
            "Episode-ID": "bad_fk", "time": 0.0, "joint_1_position": 0.0,
            "end_effector_x": 1.1, "end_effector_y": 0.0, "end_effector_z": 0.0,
        }],
        "simulation_type": "robotics",
        "robotics_limits": limits,
        "urdf_xml": _SIMPLE_URDF,
        "run_ai": False,
    })
    invalid = client.post("/v1/validate/physics-only", json={
        "data": [{"joint_1_position": 0.0}],
        "simulation_type": "robotics",
        "urdf_xml": "<robot",
    })

    assert passing.status_code == mismatched.status_code == 200
    assert invalid.status_code == 400
    assert next(check for check in passing.json()["robotics_checks"]
                if check["name"] == "robotics_kinematics:end_effector_position")["status"] == "passed"
    assert mismatched.json()["status"] == "failed"
    episode = mismatched.json()["episode_quality"]["episodes"][0]
    assert episode["training_ready"] is False
    assert "kinematics_mismatch" in episode["failure_labels"]


def test_urdf_kinematics_incomplete_coverage_is_a_warning_and_not_training_ready(client):
    response = client.post("/v1/validate/physics-only", json={
        "data": [
            {"episode_id": "partial", "time": 0.0, "joint_1_position": 0.0},
            {"episode_id": "partial", "time": 0.1, "joint_1_position": 0.0,
             "end_effector_x": 1.0, "end_effector_y": 0.0, "end_effector_z": 0.0},
        ],
        "simulation_type": "robotics",
        "robotics_limits": {"joint_1_position": [-3.14, 3.14]},
        "urdf_xml": _SIMPLE_URDF,
        "run_ai": False,
    })

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"
    assert body["training_ready"] is False
    coverage = next(check for check in body["robotics_checks"]
                    if check["name"] == "robotics_kinematics:coverage")
    assert coverage["indices"] == [0]
    quality = body["episode_quality"]["episodes"][0]
    assert quality["training_ready"] is False
    assert "kinematics_unavailable" in quality["failure_labels"]
    assert quality["flagged_rows"] == [0]


def test_prismatic_joint_urdf_allows_meter_units(client):
    prismatic_urdf = """<robot name="slide">
      <link name="base"/><link name="tool"/>
      <joint name="slide" type="prismatic"><parent link="base"/><child link="tool"/>
        <axis xyz="0 0 1"/>
      </joint>
    </robot>"""
    response = client.post("/v1/validate/physics-only", json={
        "data": [{
            "joint_slide_position": 0.25,
            "end_effector_x": 0.0,
            "end_effector_y": 0.0,
            "end_effector_z": 0.25,
        }],
        "simulation_type": "robotics",
        "robotics_limits": {"joint_slide_position": [-1.0, 1.0]},
        "units": {"joint_slide_position": "m"},
        "urdf_xml": prismatic_urdf,
        "run_ai": False,
    })
    wrong_unit = client.post("/v1/validate/physics-only", json={
        "data": [{"joint_slide_position": 0.25}],
        "simulation_type": "robotics",
        "units": {"joint_slide_position": "rad"},
        "urdf_xml": prismatic_urdf,
    })

    assert response.status_code == 200
    assert response.json()["robotics_summary"]["unit_conversions"] == {
        "joint_slide_position": "m->m"
    }
    assert wrong_unit.status_code == 400


def test_urdf_kinematics_respects_configured_sample_cap(client, monkeypatch):
    from dataclasses import replace

    import api.server as server

    monkeypatch.setattr(
        server, "settings", replace(server.settings, max_kinematics_samples=1)
    )
    response = client.post("/v1/validate/physics-only", json={
        "data": [
            {"joint_1_position": 0.0, "end_effector_x": 1.0,
             "end_effector_y": 0.0, "end_effector_z": 0.0},
            {"joint_1_position": 0.1, "end_effector_x": 1.0,
             "end_effector_y": 0.1, "end_effector_z": 0.0},
        ],
        "simulation_type": "robotics",
        "urdf_xml": _SIMPLE_URDF,
    })

    assert response.status_code == 413
    assert response.json()["error"]["details"]["limit"] == 1


def test_robotics_general_analysis_is_opt_in_and_comparison_only(client, monkeypatch):
    import api.server as server

    monkeypatch.setattr(server, "APIE_AVAILABLE", False)
    monkeypatch.setattr(server, "_apie_engine", None)
    monkeypatch.setattr(server, "dimensional_validate", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        server,
        "_serialize_dimensional",
        lambda *args, **kwargs: {"status": "failed", "trials_excluded": 1},
    )
    payload = {
        "data": [{"time": 0, "joint_1_position": 0}, {"time": 0.1, "joint_1_position": 0.1}],
        "simulation_type": "robotics",
        "robotics_limits": {"joint_1_position": [-1, 1]},
        "run_ai": False,
    }
    default = client.post("/v1/validate", json=payload).json()
    opted_in = client.post("/v1/validate", json={**payload, "run_general": True}).json()

    assert "general_analysis" not in default
    assert opted_in["general_analysis"]["comparison_only"] is True
    assert opted_in["status"] == default["status"]
    assert opted_in["training_ready"] == default["training_ready"]
    assert opted_in["exclusions"] == default["exclusions"]


def test_robotics_declared_degrees_match_radian_data_and_report_evidence(client):
    degree_rows = [
        {"time": 0.0, "joint_1_position": 0.0},
        {"time": 0.1, "joint_1_position": 120.0},
    ]
    radian_rows = [
        {"time": 0.0, "joint_1_position": 0.0},
        {"time": 0.1, "joint_1_position": 120.0 * 3.141592653589793 / 180.0},
    ]
    limits = {"joint_1_position": [-1.5, 1.5]}
    degree_response = client.post("/v1/validate/physics-only", json={
        "data": degree_rows,
        "simulation_type": "robotics",
        "robotics_limits": limits,
        "units": {"joint_1_position": "deg"},
    }).json()
    radian_response = client.post("/v1/validate/physics-only", json={
        "data": radian_rows,
        "simulation_type": "robotics",
        "robotics_limits": limits,
    }).json()

    assert degree_response["status"] == radian_response["status"] == "failed"
    assert degree_response["robotics_checks"] == radian_response["robotics_checks"]
    assert degree_response["exclusions"] == radian_response["exclusions"]
    evidence = next(item for item in degree_response["robotics_evidence"] if item["sample_index"] == 1)
    assert evidence["observed"] == pytest.approx(2.09439510239)
    assert evidence["signal"] == "joint_1_position"
    assert degree_response["robotics_summary"]["unit_conversions"] == {"joint_1_position": "deg->rad"}


def test_robotics_units_for_unknown_signal_are_bad_request(client):
    response = client.post("/v1/validate/physics-only", json={
        "data": [{"joint_1_position": 0.0}],
        "simulation_type": "robotics",
        "units": {"joint_2_position": "deg"},
    })
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"
    assert "not in the data" in response.json()["error"]["message"]


def test_physical_ai_stream_sync_endpoint_pass_and_fail(client):
    failed = client.post("/v1/streams/sync", json={
        "streams": {"camera": [0.0, 0.1, 0.2], "state": [0.2, 0.3, 0.4]},
        "tolerance_seconds": 0.05,
    })
    aligned = client.post("/v1/streams/sync", json={
        "streams": {"camera": [0.0, 0.1, 0.2], "state": [0.01, 0.11, 0.21]},
        "tolerance_seconds": 0.05,
    })

    assert failed.status_code == aligned.status_code == 200
    assert failed.json()["verdict"] == "failed"
    assert aligned.json()["verdict"] == "passed"
    assert failed.json()["streams"]["state"]["median_offset_seconds"] == pytest.approx(0.2)


def test_stream_sync_requires_two_nonempty_streams_and_enforces_sample_limit(client, monkeypatch):
    from dataclasses import replace

    import api.server as server

    single = client.post("/v1/streams/sync", json={"streams": {"camera": [0.0]}})
    empty = client.post("/v1/streams/sync", json={
        "streams": {"camera": [0.0], "state": []},
    })
    monkeypatch.setattr(server, "settings", replace(server.settings, max_rows=3))
    oversized = client.post("/v1/streams/sync", json={
        "streams": {"camera": [0.0, 0.1], "state": [0.0, 0.1]},
    })

    assert single.status_code == 422
    assert empty.status_code == 422
    assert oversized.status_code == 413


def test_sim_real_compare_endpoint_reports_velocity_drift_and_one_sided_signals(client):
    sim = [
        {"episode_id": "s", "t": i * 0.1, "joint_1_position": i * 0.3, "sim_only": i}
        for i in range(10)
    ]
    real = [
        {"episode_id": "r", "t": i * 0.1, "joint_1_position": i * 0.1}
        for i in range(10)
    ]
    response = client.post("/v1/compare/sim-real", json={
        "sim_data": sim,
        "real_data": real,
        "robotics_limits": {"joint_1_position": [-10, 10]},
    })

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "drift_detected"
    assert body["signals"]["joint_1_velocity_fd"]["overlap"] < 0.5
    assert body["signals_only_in_sim"] == ["sim_only"]


def test_sim_real_endpoint_normalizes_declared_degrees_before_comparison(client):
    radians = [0.0, 0.1, 0.2, 0.3]
    response = client.post("/v1/compare/sim-real", json={
        "sim_data": [{"t": i * 0.1, "joint_1_position": value}
                     for i, value in enumerate(radians)],
        "real_data": [{"t": i * 0.1, "joint_1_position": value * 180 / 3.141592653589793}
                      for i, value in enumerate(radians)],
        "real_units": {"joint_1_position": "deg"},
        "robotics_limits": {"joint_1_position": [-1.0, 1.0]},
    })

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "aligned"
    assert body["signals"]["joint_1_position"]["overlap"] == pytest.approx(1.0)
    assert body["unit_conversions"]["real"] == {"joint_1_position": "deg->rad"}


def test_sim_real_endpoint_does_not_call_metadata_only_tables_aligned(client):
    response = client.post("/v1/compare/sim-real", json={
        "sim_data": [{"episode_id": "s", "time": 0.0}],
        "real_data": [{"episode_id": "r", "time": 0.0}],
    })

    assert response.status_code == 200
    assert response.json()["verdict"] == "insufficient_data"


def test_sim_real_endpoint_rejects_empty_data_sides(client):
    response = client.post("/v1/compare/sim-real", json={
        "sim_data": [],
        "real_data": [{"joint_1_position": 0.0}],
    })
    assert response.status_code == 422
