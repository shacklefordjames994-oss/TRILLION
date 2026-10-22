from optimus_swarm.environmental_cues import (
    AuthorityState,
    EnvironmentalInterpretation,
    EvidenceClass,
    FeedState,
    evaluate_environment,
)
from optimus_swarm.kill_switch import HumanAuthorityKillSwitch
from optimus_swarm.simulation_decision import SimulationDecisionLog, record_simulation_decision
from optimus_swarm.timeline_store import TimelineStore


def evaluation():
    item = EnvironmentalInterpretation(
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
        model_version="test-model-1",
    )
    return evaluate_environment(item, now_ms=10000, authority_state=AuthorityState.CLEAR)


def test_unauthorized_actor_cannot_approve():
    switch = HumanAuthorityKillSwitch({"human-001"})
    decision = SimulationDecisionLog(switch).submit(
        evaluation(),
        actor_id="robot-B",
        authorization_id="approve-1",
        choice="APPROVE",
    )
    assert decision.code == "UNAUTHORIZED"
    assert switch.state.latched is True
    assert switch.state.revision == 1


def test_approval_while_latched_is_blocked_and_does_not_reset():
    switch = HumanAuthorityKillSwitch({"human-001"})
    decision = SimulationDecisionLog(switch).submit(
        evaluation(),
        actor_id="human-001",
        authorization_id="approve-1",
        choice="APPROVE",
    )
    assert decision.code == "BLOCKED"
    assert decision.inhibit_cleared is False
    assert decision.physical_execution_permitted is False
    assert switch.state.latched is True
    assert switch.state.revision == 1


def test_clear_latch_approval_admits_simulation_only():
    switch = HumanAuthorityKillSwitch({"human-001"})
    switch.reset("human-001", "reset-1", "Clear for a simulation check")
    revision = switch.state.revision
    decision = SimulationDecisionLog(switch).submit(
        evaluation(),
        actor_id="human-001",
        authorization_id="approve-1",
        choice="APPROVE",
    )
    assert decision.code == "SIMULATION_ADMITTED"
    assert decision.physical_execution_permitted is False
    assert decision.inhibit_cleared is False
    assert switch.state.latched is False
    assert switch.state.revision == revision
    assert switch.permits_physical_execution() is False


def test_reject_and_replay_do_not_clear_the_latch(tmp_path):
    switch = HumanAuthorityKillSwitch({"human-001"})
    log = SimulationDecisionLog(switch)
    rejected = log.submit(
        evaluation(),
        actor_id="human-001",
        authorization_id="reject-1",
        choice="REJECT",
    )
    replayed = log.submit(
        evaluation(),
        actor_id="human-001",
        authorization_id="reject-1",
        choice="APPROVE",
    )
    assert rejected.code == "SIMULATION_REJECTED"
    assert replayed.code == "REPLAYED_AUTHORIZATION"
    assert switch.state.latched is True

    store = TimelineStore(tmp_path / "timeline.db")
    record_simulation_decision(
        store,
        rejected,
        robot_id="robot-sim-01",
        sequence_number=1,
        now_ms=10000,
    )
    event = next(entry.event for entry in store.replay() if entry.kind == "EVENT")
    assert event["event_type"] == "AUTHORITY_STATE"
    assert event["payload"]["physical_execution_permitted"] is False
    assert event["payload"]["inhibit_cleared"] is False
