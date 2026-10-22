from dataclasses import replace

from optimus_swarm.brain_models import AuthorityState, BrainSnapshot, EvidenceClass, FeedStatus, RobotView
from optimus_swarm.brain_projection import project_snapshot
from optimus_swarm.brain_validation import validate_snapshot


def make_snapshot():
    robot = RobotView(
        robot_id="sim-robot-01",
        feed_status=FeedStatus.LIVE,
        updated_at_ms=1000,
        pose_evidence_class=EvidenceClass.SIMULATED,
        pose_m=(1.0, 2.0, 0.0),
        objects=(),
        unknown_region_count=0,
    )
    return BrainSnapshot(
        snapshot_id="snapshot-001",
        created_at_ms=1000,
        robot_views=(robot,),
        tasks=(),
        evidence=(),
        authority_state=AuthorityState.CLEAR,
        authority_revision=1,
        physical_execution_enabled=False,
    )


def test_fresh_simulation_snapshot_is_accepted():
    result = validate_snapshot(make_snapshot(), now_ms=1500)
    assert result.accepted is True
    assert result.physical_execution_enabled is False


def test_stale_snapshot_is_rejected():
    result = validate_snapshot(make_snapshot(), now_ms=5000)
    assert result.accepted is False
    assert "SNAPSHOT_STALE" in result.issues


def test_latched_authority_is_not_hidden():
    snapshot = replace(make_snapshot(), authority_state=AuthorityState.LATCHED)
    result = validate_snapshot(snapshot, now_ms=1500)
    assert result.accepted is False
    assert "AUTHORITY_INHIBIT_LATCHED" in result.issues


def test_physical_execution_flag_is_rejected():
    snapshot = replace(make_snapshot(), physical_execution_enabled=True)
    result = validate_snapshot(snapshot, now_ms=1500)
    assert result.accepted is False
    assert "PHYSICAL_EXECUTION_FLAG_MUST_BE_FALSE" in result.issues


def test_projection_preserves_simulated_evidence():
    projected = project_snapshot(make_snapshot())
    assert projected["robots"][0]["pose_evidence_class"] == "SIMULATED"
    assert projected["physical_execution_enabled"] is False
