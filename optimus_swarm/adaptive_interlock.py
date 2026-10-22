from dataclasses import dataclass

from optimus_swarm.adaptive_response import AdaptiveDecision, ResponseGrade
from optimus_swarm.hardware_interlock import HardwareSafetyChain


@dataclass(frozen=True)
class InterlockDecision:
    stop_demanded: bool
    chain_reason: str
    motion_power: bool
    actuator_output_enabled: bool = False
    hardware_reset_performed: bool = False
    physical_execution_permitted: bool = False


_STOP_GRADES = {
    ResponseGrade.G3_CRITICAL_INHIBIT,
    ResponseGrade.G4_DATA_INVALID,
}


def apply_hardware_interlock(
    chain: HardwareSafetyChain,
    decision: AdaptiveDecision,
    *,
    actor_id: str,
    now_ms: int,
) -> InterlockDecision:
    """
    A software grade may demand a stop. It cannot reset the chain or enable an actuator.
    """
    stop = decision.response_grade in _STOP_GRADES or not decision.accepted
    if stop:
        chain.demand_stop(actor_id or "adaptive-engine", decision.response_grade.value)
    status = chain.evaluate(now_ms)
    allowed, code = chain.actuator_command("proposed-motion")
    if allowed or status.actuator_output_enabled:
        code = "OUTPUT_REFUSED"
    return InterlockDecision(
        stop_demanded=stop,
        chain_reason=status.reason if code == "NO_SAFETY_RATED_OUTPUT" else code,
        motion_power=status.motion_power,
        actuator_output_enabled=False,
        hardware_reset_performed=False,
        physical_execution_permitted=False,
    )
