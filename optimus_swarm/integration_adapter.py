from dataclasses import dataclass

from optimus_swarm.secure_command_models import CommandDecision, DecisionStatus


@dataclass(frozen=True)
class SimulationEvent:
    event_id: str
    command_id: str
    operation: str
    payload_digest: str
    recorded_at_ms: int
    mode: str = "SIMULATION_ONLY"


class SimulationAdapter:
    """
    Records admitted simulation requests.
    This prototype does not execute robotics physics or control hardware.
    """

    def __init__(self):
        self._events: dict[str, SimulationEvent] = {}

    def record(
        self,
        *,
        decision: CommandDecision,
        operation: str,
        payload_digest: str,
        now_ms: int,
    ) -> SimulationEvent:
        if decision.status != DecisionStatus.ACCEPTED:
            raise PermissionError("COMMAND_NOT_ACCEPTED")
        if not decision.simulation_permitted:
            raise PermissionError("SIMULATION_NOT_PERMITTED")
        if decision.physical_execution_authorized:
            raise PermissionError("PHYSICAL_EXECUTION_MUST_REMAIN_DISABLED")
        if not operation or not payload_digest or now_ms < 0:
            raise ValueError("INVALID_SIMULATION_EVENT")
        if decision.command_id in self._events:
            raise ValueError("DUPLICATE_SIMULATION_EVENT")

        event = SimulationEvent(
            event_id=f"sim:{decision.command_id}",
            command_id=decision.command_id,
            operation=operation,
            payload_digest=payload_digest,
            recorded_at_ms=now_ms,
        )
        self._events[decision.command_id] = event
        return event

    def events(self) -> tuple[SimulationEvent, ...]:
        return tuple(self._events[key] for key in sorted(self._events))
