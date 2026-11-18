"""Context-safe MCP pagination: compact episode summaries, top-N offending
episodes, and on-demand evidence retrieval."""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")

import simapi_mcp as server  # noqa: E402

LIMITS = {"joint_1_position": (-10, 10), "joint_1_velocity": (-10, 10),
          "joint_1_torque": (-70, 70)}


def _good_episode(name, n=40):
    return [{"episode_id": name, "time": i * 0.02,
             "joint_1_position": 0.05 * i, "joint_1_velocity": 0.5,
             "joint_1_torque": 3.0} for i in range(n)]


def _bad_episode(name, n=40, teleport=True, limit=True):
    rows = []
    for i in range(n):
        rows.append({"episode_id": name, "time": i * 0.02,
                     "joint_1_position": 99.0 if limit else 0.05 * i,
                     "joint_1_velocity": 900.0 if (teleport and i == 20) else 0.5,
                     "joint_1_torque": 3.0})
    return rows


def test_top_five_offending_episodes_returned_by_default():
    rows = []
    for index in range(8):
        rows += _bad_episode(f"bad_{index}")
    rows += _good_episode("good_0") + _good_episode("good_1")

    result = server.validate_and_filter_episodes(rows=rows, robotics_limits=LIMITS)

    assert result["training_ready_episodes"] == ["good_0", "good_1"]
    assert result["rejected_episodes_total"] == 8
    assert result["omitted_rejected_episodes"] == 3
    assert len(result["rejected_episodes"]) == 5
    assert result["summary"]["episodes_ready"] == 2
    # The response tells the agent how to page deeper.
    assert result["run_id"]
    assert "get_episode_evidence" in (result["detail"] or "")


def test_inline_episodes_are_compact():
    result = server.validate_and_filter_episodes(
        rows=_bad_episode("bad"), robotics_limits=LIMITS
    )
    episode = result["rejected_episodes"][0]
    assert set(episode) == {"episode_id", "samples", "verdict",
                            "failure_labels", "failed_check_names"}
    # Check names only — no per-check detail strings inline.
    assert isinstance(episode["failed_check_names"], list)
    assert all(isinstance(name, str) for name in episode["failed_check_names"])


def test_ranking_puts_worst_episode_first():
    rows = _bad_episode("one_failure", teleport=False)  # limit violation only
    rows += _bad_episode("two_failures")                # limit + teleport
    result = server.validate_and_filter_episodes(rows=rows, robotics_limits=LIMITS)
    assert result["rejected_episodes"][0]["episode_id"] == "two_failures"
    assert len(result["rejected_episodes"][0]["failed_check_names"]) > \
        len(result["rejected_episodes"][1]["failed_check_names"])


def test_zero_inline_episodes_still_reports_totals():
    rows = _bad_episode("bad")
    result = server.validate_and_filter_episodes(
        rows=rows, robotics_limits=LIMITS, max_rejected_episodes=0
    )
    assert result["rejected_episodes"] == []
    assert result["rejected_episodes_total"] == 1
    assert result["omitted_rejected_episodes"] == 1


def test_max_rejected_episodes_is_validated():
    with pytest.raises(ValueError):
        server.validate_and_filter_episodes(
            rows=_good_episode("g"), robotics_limits=LIMITS,
            max_rejected_episodes=-1,
        )


def test_empty_rows_fail_closed_with_totals():
    result = server.validate_and_filter_episodes(rows=[], robotics_limits=LIMITS)
    assert result["training_ready_episodes"] == []
    assert result["rejected_episodes_total"] == 1
    assert result["rejected_by_check"] == {"no_data": 1}


def test_get_episode_evidence_returns_full_details():
    rows = _bad_episode("bad") + _good_episode("good")
    server.validate_and_filter_episodes(
        rows=rows, robotics_limits=LIMITS, run_id="evidence-test-run"
    )
    evidence = server.get_episode_evidence("evidence-test-run", "bad")
    assert evidence["verdict"] == "failed"
    assert evidence["flagged_sample_count"] > 0
    assert any("detail" in check for check in evidence["failed_checks"])
    assert evidence["first_violation_rows"], "sample rows must be inspectable"
    # Training-ready episodes are inspectable too.
    good = server.get_episode_evidence("evidence-test-run", "good")
    assert good["verdict"] == "passed"
    assert good["failed_checks"] == []


def test_get_episode_evidence_errors_are_explicit():
    rows = _bad_episode("bad")
    result = server.validate_and_filter_episodes(rows=rows, robotics_limits=LIMITS)
    run_id = result["run_id"]
    with pytest.raises(ValueError, match="Unknown run_id"):
        server.get_episode_evidence("no-such-run", "bad")
    with pytest.raises(ValueError, match="no episode"):
        server.get_episode_evidence(run_id, "no-such-episode")


def test_explicit_run_id_replaces_its_own_entry():
    # A caller-chosen run_id is the caller's key: reusing it updates that
    # entry rather than spawning a near-duplicate run.
    server.validate_and_filter_episodes(rows=_good_episode("g1"), run_id="dup-run")
    server.validate_and_filter_episodes(rows=_good_episode("g2"), run_id="dup-run")
    with pytest.raises(ValueError, match="no episode"):
        server.get_episode_evidence("dup-run", "g1")  # replaced
    evidence = server.get_episode_evidence("dup-run", "g2")
    assert evidence["episode_id"] == "g2"


def test_workspace_floor_reaches_the_mcp_filter():
    urdf = """
    <robot name="arm">
      <link name="base"/><link name="tip"/>
      <joint name="joint1" type="revolute">
        <parent link="base"/><child link="tip"/>
        <origin xyz="0 0 0.1"/><axis xyz="0 0 1"/>
      </joint>
    </robot>
    """
    rows = [{"episode_id": "low", "time": i * 0.02, "joint_1_position": 0.0}
            for i in range(20)]
    result = server.validate_and_filter_episodes(
        rows=rows, robotics_limits={}, urdf_xml=urdf, min_workspace_z=0.2,
    )
    assert "low" not in result["training_ready_episodes"]
    assert any(name.startswith("robotics_workspace_floor")
               for name in result["rejected_by_check"])
