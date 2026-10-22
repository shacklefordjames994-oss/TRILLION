import pytest

from optimus_swarm.incident_response import IncidentResponseEngine
from optimus_swarm.integrity import TamperEvidentLedger
from optimus_swarm.kill_switch import HumanAuthorityKillSwitch


@pytest.fixture
def system():
    key = b"test-key-material-at-least-32-bytes"
    ledger = TamperEvidentLedger(key)
    switch = HumanAuthorityKillSwitch({"human-001"})
    quarantined = set()

    def quarantine(record_id, incident_id):
        quarantined.add(record_id)
        return True

    engine = IncidentResponseEngine(
        kill_switch=switch,
        ledger=ledger,
        authorized_reviewers={"human-001"},
        quarantine_record=quarantine,
    )
    return engine, switch, ledger, quarantined


def test_critical_integrity_event_requests_inhibit(system):
    engine, switch, _, _ = system

    result = engine.report(
        robot_id="robot-007",
        code="SIGNATURE_INVALID",
        description="Policy signature verification failed",
        evidence={"policy_id": "policy-demo"},
        policy_revision=4,
    )

    assert result.accepted
    assert switch.state.latched
    assert "INHIBIT_REQUESTED" in result.actions


def test_memory_record_is_quarantined(system):
    engine, _, _, quarantined = system

    result = engine.report(
        robot_id="robot-007",
        code="UNAPPROVED_BEHAVIOR",
        description="Unapproved simulation action",
        evidence={"action": "unknown_action"},
        policy_revision=4,
        memory_record_id="experience-123",
    )

    assert result.accepted
    assert "experience-123" in quarantined
    assert engine.is_quarantined("experience-123")


def test_unknown_incident_cannot_be_reviewed(system):
    engine, _, _, _ = system

    with pytest.raises(KeyError):
        engine.approve_review(
            "missing-incident",
            "human-001",
            "review-001",
            "reject",
        )


def test_unauthorized_reviewer_is_rejected(system):
    engine, _, _, _ = system

    result = engine.report(
        "robot-007",
        "UNAPPROVED_BEHAVIOR",
        "Test",
        {"action": "unknown"},
        1,
    )

    with pytest.raises(PermissionError):
        engine.approve_review(
            result.incident_id,
            "agent-001",
            "review-001",
            "reject",
        )


def test_review_does_not_clear_safety_latch(system):
    engine, switch, _, _ = system

    result = engine.report(
        "robot-007",
        "SIGNATURE_INVALID",
        "Test",
        {"policy_id": "policy-demo"},
        1,
    )
    assert switch.state.latched

    engine.approve_review(
        result.incident_id,
        "human-001",
        "review-001",
        "investigated",
    )

    assert switch.state.latched
    assert not switch.permits_physical_execution()


def test_inhibit_happens_when_evidence_cannot_be_digested(system):
    engine, switch, _, _ = system

    result = engine.report(
        robot_id="robot-007",
        code="AUDIT_INTEGRITY_FAILURE",
        description="Evidence could not be serialized",
        evidence={"blob": object()},
        policy_revision=3,
    )

    assert switch.state.latched
    assert "INHIBIT_REQUESTED" in result.actions
    assert "EVIDENCE_DIGEST_FAILED" in result.actions
    incident = engine.get_incident(result.incident_id)
    assert incident is not None
    assert incident.evidence_digest == "UNAVAILABLE"
