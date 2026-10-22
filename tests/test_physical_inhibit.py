import pytest

from optimus_swarm.hardware_interlock import HardwareSafetyChain
from optimus_swarm.kill_switch import HumanAuthorityKillSwitch
from optimus_swarm.physical_inhibit import PhysicalExecutionDenied, PhysicalExecutionInhibit


def test_inhibit_is_engaged_and_has_no_release():
    inhibit = PhysicalExecutionInhibit()
    assert inhibit.engaged() is True
    assert inhibit.permits() is False
    assert inhibit.authorize({"physical_execution_permitted": True}) == (False, "PHYSICAL_EXECUTION_INHIBITED")
    with pytest.raises(PhysicalExecutionDenied):
        inhibit.release("human-001", "approval-1")
    assert inhibit.permits() is False


def test_simulation_reset_does_not_release_physical_inhibit():
    switch = HumanAuthorityKillSwitch({"human-001"})
    switch.reset("human-001", "approval-1", "Clear the simulation latch")
    assert switch.permits_simulation() is True
    assert switch.permits_physical_execution() is False


def test_closed_hardware_chain_still_inhibits_actuator_output():
    chain = HardwareSafetyChain({"human-001"})
    chain.release_estop("human-001")
    chain.pulse("safety-plc", 10000)
    chain.hardware_reset("human-001", "channel-1", "Operator reset", 10000)
    chain.report_feedback(True, 10000)
    assert chain.evaluate(10000).motion_power is True
    assert chain.actuator_command("move-joint") == (False, "NO_SAFETY_RATED_OUTPUT")
    assert PhysicalExecutionInhibit().permits() is False
