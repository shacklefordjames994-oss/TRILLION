from dataclasses import dataclass

from optimus_swarm.command_models import CommandDecision, CommandStatus
from optimus_swarm.physical_inhibit import PhysicalExecutionInhibit


@dataclass(frozen=True)
class SimulationReceipt:
    command_id: str
    accepted: bool
    result: str
    physical_execution_authorized: bool = False


class SimulationAdapter:
    def process(self, decision: CommandDecision) -> SimulationReceipt:
        allowed, _code = PhysicalExecutionInhibit().authorize(decision)
        if decision.physical_execution_authorized or allowed:
            return SimulationReceipt(
                command_id=decision.command_id,
                accepted=False,
                result="PHYSICAL_AUTHORIZATION_FORBIDDEN",
            )

        if decision.status != CommandStatus.ACCEPTED or not decision.simulation_permitted:
            return SimulationReceipt(
                command_id=decision.command_id,
                accepted=False,
                result="COMMAND_NOT_ADMITTED",
            )

        return SimulationReceipt(
            command_id=decision.command_id,
            accepted=True,
            result="SIMULATION_EVENT_RECORDED",
        )
