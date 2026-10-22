from optimus_swarm.cue_review import decide_review, record_cues
from optimus_swarm.environmental_cues import (
    AuthorityState,
    EnvironmentalInterpretation,
    EvidenceClass,
    FeedState,
    evaluate_environment,
)
from optimus_swarm.timeline_store import TimelineStore


def sample(**overrides):
    data = dict(
        interpretation_id="interp-001",
        robot_id="robot-sim-01",
        captured_at_ms=9500,
        received_at_ms=9550,
        source_id="synthetic-sensor",
        evidence_id="evidence-001",
        evidence_class=EvidenceClass.SIMULATED,
        feed_state=FeedState.LIVE,
        kind="OBJECT_DETECTED",
        confidence=0.92,
        distance_m=2.0,
        path_intersects_unknown=False,
        conflicting_sources=(),
        model_version="test-model-1",
        details="Synthetic test input",
    )
    data.update(overrides)
    return EnvironmentalInterpretation(**data)


def test_clear_object_cue_is_visible_and_motionless():
    evaluation = evaluate_environment(sample(), now_ms=10000, authority_state=AuthorityState.CLEAR)
    decision = decide_review(evaluation, authority_latched=False)
    assert decision.code == "SIMULATION_VISIBLE"
    assert decision.physical_execution_permitted is False
    assert decision.inhibit_cleared is False


def test_unknown_path_waits_for_a_named_reviewer(tmp_path):
    evaluation = evaluate_environment(
        sample(path_intersects_unknown=True),
        now_ms=10000,
        authority_state=AuthorityState.CLEAR,
    )
    waiting = decide_review(evaluation, authority_latched=False)
    rejected = decide_review(evaluation, authority_latched=False, acknowledged=True, reviewer_id="  ")
    accepted = decide_review(
        evaluation,
        authority_latched=False,
        acknowledged=True,
        reviewer_id="human-operator-1",
    )

    assert waiting.code == "AWAITING_REVIEW"
    assert rejected.code == "REVIEW_REJECTED"
    assert accepted.code == "SIMULATION_VISIBLE"
    assert accepted.inhibit_cleared is False
    assert accepted.physical_execution_permitted is False


def test_acknowledgement_does_not_clear_a_latch():
    evaluation = evaluate_environment(sample(), now_ms=10000, authority_state=AuthorityState.LATCHED)
    decision = decide_review(
        evaluation,
        authority_latched=True,
        acknowledged=True,
        reviewer_id="human-operator-1",
    )
    assert decision.code == "BLOCKED"
    assert decision.inhibit_cleared is False


def test_recorded_cues_replay_without_changing_class(tmp_path):
    evaluation = evaluate_environment(
        sample(path_intersects_unknown=True),
        now_ms=10000,
        authority_state=AuthorityState.LATCHED,
    )
    store = TimelineStore(tmp_path / "timeline.db")
    record_cues(store, evaluation, start_sequence=1, received_at_ms=10000)
    events = [entry.event for entry in store.replay() if entry.kind == "EVENT"]

    assert [event["evidence_class"] for event in events] == ["SIMULATED", "SIMULATED", "SIMULATED"]
    assert events[-1]["event_type"] == "AUTHORITY_STATE"
    assert all(event["payload"]["physical_execution_permitted"] is False for event in events)
