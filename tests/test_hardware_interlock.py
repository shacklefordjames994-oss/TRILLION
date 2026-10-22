import pytest

from optimus_swarm.hardware_interlock import HardwareSafetyChain, HardwareStopRequired
from optimus_swarm.incident_response import IncidentResponseEngine
from optimus_swarm.integrity import TamperEvidentLedger
from optimus_swarm.kill_switch import HumanAuthorityKillSwitch


def test_chain_boots_open_and_refuses_actuators():
    chain = HardwareSafetyChain({"human-001"})
    status = chain.evaluate(0)

    assert status.motion_power is False
    assert status.estop_loop_closed is False
    assert status.actuator_output_enabled is False
    assert chain.actuator_command("joint_torque") == (False, "NO_SAFETY_RATED_OUTPUT")


def test_robot_cannot_reset_or_close_the_guard():
    chain = HardwareSafetyChain({"human-001"})
    chain.open_guard("person in cell")

    with pytest.raises(HardwareStopRequired):
        chain.hardware_reset("robot-007", "channel-1", "attempt", 0)
    with pytest.raises(HardwareStopRequired):
        chain.close_guard("robot-007")
    assert chain.evaluate(0).guard_closed is False
    assert chain.evaluate(0).motion_power is False


def test_robot_pulse_does_not_refresh_the_watchdog():
    chain = HardwareSafetyChain({"human-001"}, watchdog_ms=250)

    assert chain.pulse("robot-007", 1000) is False
    chain.release_estop("human-001")

    assert chain.evaluate(1000).watchdog_closed is False


def test_stale_or_reversed_clock_fails_closed():
    chain = HardwareSafetyChain({"human-001"}, watchdog_ms=250)
    chain.release_estop("human-001")
    assert chain.pulse("safety-plc", 1000) is True
    chain.hardware_reset("human-001", "channel-1", "checked", 1100)

    assert chain.evaluate(1100).reason == "FEEDBACK_DEENERGIZED"
    assert chain.evaluate(1500).watchdog_closed is False
    assert chain.evaluate(900).watchdog_closed is False
    assert chain.evaluate(-1).reason == "SAFETY_CHAIN_UNAVAILABLE"
    assert chain.evaluate(-1).motion_power is False


def test_energized_feedback_while_open_latches_a_fault():
    chain = HardwareSafetyChain({"human-001"})
    status = chain.report_feedback(True, 0)

    assert status.fault_latched is True
    assert status.motion_power is False
    chain.release_estop("human-001")
    chain.pulse("safety-plc", 10)
    with pytest.raises(HardwareStopRequired):
        chain.hardware_reset("human-001", "channel-2", "reset", 10)


def test_healthy_chain_still_has_no_actuator_output():
    chain = HardwareSafetyChain({"human-001"}, watchdog_ms=250)
    chain.release_estop("human-001")
    chain.pulse("safety-plc", 100)
    chain.hardware_reset("human-001", "channel-3", "contacts checked", 100)
    status = chain.report_feedback(True, 120)

    assert status.motion_power is True
    assert status.actuator_output_enabled is False
    assert chain.actuator_command("joint_torque") == (False, "NO_SAFETY_RATED_OUTPUT")


def test_software_reset_does_not_close_the_hardware_chain():
    switch = HumanAuthorityKillSwitch({"human-001"})
    chain = HardwareSafetyChain({"human-001"})
    ledger = TamperEvidentLedger(b"z" * 32)
    engine = IncidentResponseEngine(
        kill_switch=switch,
        ledger=ledger,
        authorized_reviewers={"human-001"},
        quarantine_record=lambda _record, _incident: True,
        hardware=chain,
    )

    result = engine.report(
        robot_id="robot-007",
        code="SIGNATURE_INVALID",
        description="Open the hardware loop too",
        evidence={"policy_id": "policy-demo"},
        policy_revision=2,
    )
    assert "HARDWARE_STOP_DEMANDED" in result.actions
    assert chain.evaluate(0).estop_loop_closed is False

    switch.reset("human-001", "approval-001", "Software latch only")
    engine.approve_review(result.incident_id, "human-001", "review-hw", "investigated")

    status = chain.evaluate(0)
    assert switch.permits_simulation() is True
    assert status.estop_loop_closed is False
    assert status.motion_power is False
    assert chain.actuator_command("joint_torque")[0] is False
