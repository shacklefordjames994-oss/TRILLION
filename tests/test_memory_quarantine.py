from optimus_swarm.guard import OmegaGuard
from optimus_swarm.incident_response import IncidentResponseEngine
from optimus_swarm.integrity import TamperEvidentLedger
from optimus_swarm.kill_switch import HumanAuthorityKillSwitch
from optimus_swarm.models import Experience, RetrievalContext
from optimus_swarm.swarm_memory import SwarmMemory


def _experience(status="VALIDATED", experience_id="experience-123"):
    return Experience(
        experience_id=experience_id,
        origin_robot_id="omega-a",
        task_type="pick_place",
        environment_version="cell-v3",
        model_version="omega-0.4",
        outcome="success",
        source="SIMULATION",
        validation_status=status,
        evidence_hash="ab" * 32,
        confidence=0.97,
    )


def _context():
    return RetrievalContext(
        receiving_robot_id="omega-b",
        task_type="pick_place",
        environment_version="cell-v3",
        model_version="omega-0.4",
    )


def test_validated_record_is_hidden_after_quarantine(tmp_path):
    memory = SwarmMemory(str(tmp_path / "swarm.sqlite3"))
    memory.publish(_experience())
    guard = OmegaGuard()

    assert len(memory.retrieve_candidates(_context(), guard)) == 1
    assert memory.quarantine("experience-123", "incident-1") is True
    assert memory.retrieve_candidates(_context(), guard) == []


def test_engine_quarantine_blocks_shared_memory(tmp_path):
    switch = HumanAuthorityKillSwitch({"human-001"})
    switch.reset("human-001", "approval-010", "Retrieval test")
    memory = SwarmMemory(str(tmp_path / "swarm.sqlite3"), kill_switch=switch)
    memory.publish(_experience())
    memory.publish(_experience(experience_id="experience-keep"))
    engine = IncidentResponseEngine(
        kill_switch=switch,
        ledger=TamperEvidentLedger(b"y" * 32),
        authorized_reviewers={"human-001"},
        quarantine_record=memory.quarantine,
    )
    guard = OmegaGuard()

    result = engine.report(
        robot_id="robot-007",
        code="UNAPPROVED_BEHAVIOR",
        description="Suspect grasp memory",
        evidence={"action": "unknown_action"},
        policy_revision=4,
        memory_record_id="experience-123",
    )

    assert "MEMORY_QUARANTINED" in result.actions
    found = memory.retrieve_candidates(_context(), guard)
    assert [item[0].experience_id for item in found] == ["experience-keep"]

    engine.approve_review(
        result.incident_id,
        "human-001",
        "review-010",
        "investigated",
    )
    found_after_review = memory.retrieve_candidates(_context(), guard)
    assert [item[0].experience_id for item in found_after_review] == ["experience-keep"]
    assert switch.permits_physical_execution() is False
