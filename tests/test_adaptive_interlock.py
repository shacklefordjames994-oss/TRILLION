import pytest

from optimus_swarm.adaptive_interlock import apply_hardware_interlock
from optimus_swarm.adaptive_response import AuthorityState, EnvironmentState, adaptive_response
from optimus_swarm.hardware_interlock import HardwareSafetyChain, HardwareStopRequired


def state(**changes):
    base = dict(
        distance_m=3.0,
        closing_speed_mps=0.2,
        distance_sigma_m=0.05,
        source_quality=1.0,
        freshness_quality=1.0,
        integrity_quality=1.0,
        unknown_fraction=0.0,
        hazard_severity=0.0,
        captured_at_ms=9900,
        received_at_ms=9950,
    )
    base.update(changes)
    return EnvironmentState(**base)


def healthy(chain: HardwareSafetyChain, now_ms: int = 10000) -> None:
    chain.release_estop("human-001")
    chain.pulse("safety-plc", now_ms)
    chain.hardware_reset("human-001", "channel-1", "Operator reset", now_ms)
    chain.report_feedback(True, now_ms)


def test_monitor_grade_does_not_reset_or_enable_output():
    chain = HardwareSafetyChain({"human-001"})
    decision = adaptive_response(state(), now_ms=10000, authority_state=AuthorityState.CLEAR)
    result = apply_hardware_interlock(chain, decision, actor_id="adaptive-engine", now_ms=10000)

    assert decision.response_grade.value == "G0_MONITOR"
    assert result.stop_demanded is False
    assert result.hardware_reset_performed is False
    assert result.actuator_output_enabled is False
    assert result.physical_execution_permitted is False
    assert chain.evaluate(10000).reason == "ESTOP_OPEN"


def test_critical_grade_opens_a_closed_chain_and_still_disables_output():
    chain = HardwareSafetyChain({"human-001"})
    healthy(chain)
    assert chain.evaluate(10000).motion_power is True

    decision = adaptive_response(state(distance_m=0.1), now_ms=10000, authority_state=AuthorityState.LATCHED)
    result = apply_hardware_interlock(chain, decision, actor_id="adaptive-engine", now_ms=10000)

    assert result.stop_demanded is True
    assert result.chain_reason == "FEEDBACK_DISAGREES"
    assert result.motion_power is False
    assert result.actuator_output_enabled is False
    assert result.hardware_reset_performed is False
    with pytest.raises(HardwareStopRequired):
        chain.hardware_reset("adaptive-engine", "channel-2", "software tries to reset", 10000)


def test_stale_environment_demands_stop():
    chain = HardwareSafetyChain({"human-001"})
    healthy(chain)
    decision = adaptive_response(state(captured_at_ms=1000), now_ms=10000, authority_state=AuthorityState.CLEAR)
    result = apply_hardware_interlock(chain, decision, actor_id="adaptive-engine", now_ms=10000)

    assert decision.response_grade.value == "G4_DATA_INVALID"
    assert result.stop_demanded is True
    assert chain.actuator_command("move") == (False, "NO_SAFETY_RATED_OUTPUT")
