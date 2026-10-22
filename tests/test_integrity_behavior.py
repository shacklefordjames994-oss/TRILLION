from dataclasses import replace

from optimus_swarm.integrity import TamperEvidentLedger
from optimus_swarm.behavior_guard import BehaviorGuard
from optimus_swarm.kill_switch import HumanAuthorityKillSwitch
from optimus_swarm.assurance import assess_readiness


def make_system():
    ledger = TamperEvidentLedger(b"x" * 32)
    switch = HumanAuthorityKillSwitch({"human-001"})
    switch.reset("human-001", "approval-001", "Simulation test setup")
    guard = BehaviorGuard(
        frozenset({"observe_synthetic_state"}),
        ledger,
        switch,
    )
    return ledger, switch, guard


def test_ledger_detects_record_modification():
    ledger = TamperEvidentLedger(b"x" * 32)
    record = ledger.append("robot-1", "INHIBIT", "Test")
    assert ledger.verify()

    ledger._records[0] = replace(record, reason="Altered")
    assert not ledger.verify()


def test_unknown_action_is_rejected():
    _, _, guard = make_system()
    result = guard.evaluate(
        "robot-1",
        "activate_actuator",
        {
            "mode": "SIMULATION",
            "policy_verified": True,
            "physical_actuation_requested": False,
        },
    )
    assert not result.allowed
    assert result.code == "UNAPPROVED_BEHAVIOR"


def test_physical_actuation_is_rejected():
    _, _, guard = make_system()
    result = guard.evaluate(
        "robot-1",
        "observe_synthetic_state",
        {
            "mode": "SIMULATION",
            "policy_verified": True,
            "physical_actuation_requested": True,
        },
    )
    assert not result.allowed
    assert result.code == "PHYSICAL_EXECUTION_DISABLED"


def test_latched_system_rejects_actions():
    _, switch, guard = make_system()
    switch.engage("robot-1", "Safety test")

    result = guard.evaluate(
        "robot-1",
        "observe_synthetic_state",
        {
            "mode": "SIMULATION",
            "policy_verified": True,
            "physical_actuation_requested": False,
        },
    )
    assert not result.allowed
    assert result.code == "KILL_SWITCH_LATCHED"


def test_incomplete_assurance_cannot_certify():
    report = assess_readiness({})
    assert report.status == "INCOMPLETE"
    assert report.certification_granted is False


def test_failed_assurance_evidence_blocks_readiness():
    report = assess_readiness(
        {
            "network_loss_fail_closed_tested": False,
        }
    )
    assert report.status == "BLOCKED"
    assert report.certification_granted is False
