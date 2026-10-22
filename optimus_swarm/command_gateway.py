from collections.abc import Callable

from optimus_swarm.command_models import CommandDecision, CommandEnvelope, CommandStatus
from optimus_swarm.command_policy import validate_command_shape
from optimus_swarm.inhibit_state import InhibitState

EpochValidator = Callable[[str, int], bool]
LeaseValidator = Callable[[str, str, str, int, int], bool]
ReplayReserver = Callable[[str], bool]


class CommandGateway:
    def __init__(
        self,
        *,
        coordinator_id: str,
        current_epoch: int,
        inhibit_state: InhibitState,
        epoch_validator: EpochValidator,
        lease_validator: LeaseValidator,
        replay_reserver: ReplayReserver,
    ):
        if not coordinator_id.strip() or current_epoch < 1:
            raise ValueError("Invalid coordinator configuration")

        self._coordinator_id = coordinator_id
        self._current_epoch = current_epoch
        self._inhibit = inhibit_state
        self._validate_epoch = epoch_validator
        self._validate_lease = lease_validator
        self._reserve_replay = replay_reserver

    @staticmethod
    def _decision(status, code, command_id, permitted=False):
        return CommandDecision(
            status=status,
            code=code,
            command_id=command_id or "UNKNOWN",
            simulation_permitted=permitted,
            physical_execution_authorized=False,
        )

    def authorize_simulation(self, command: CommandEnvelope, *, now_ms: int) -> CommandDecision:
        command_id = getattr(command, "command_id", "UNKNOWN")

        try:
            initial_inhibit = self._inhibit.snapshot()
        except Exception:
            return self._decision(CommandStatus.INDETERMINATE, "INHIBIT_STATE_UNAVAILABLE", command_id)

        if initial_inhibit.latched:
            return self._decision(CommandStatus.REJECTED, "SYSTEM_INHIBITED", command_id)

        valid, code = validate_command_shape(command, now_ms=now_ms)
        if not valid:
            return self._decision(CommandStatus.REJECTED, code, command_id)

        if command.coordinator_id != self._coordinator_id:
            return self._decision(CommandStatus.REJECTED, "COORDINATOR_MISMATCH", command_id)

        if command.coordinator_epoch != self._current_epoch:
            return self._decision(CommandStatus.REJECTED, "STALE_OR_UNKNOWN_EPOCH", command_id)

        try:
            if not self._validate_epoch(command.coordinator_id, command.coordinator_epoch):
                return self._decision(CommandStatus.REJECTED, "EPOCH_VALIDATION_FAILED", command_id)

            if not self._validate_lease(
                command.task_id,
                command.worker_id,
                command.lease_id,
                command.generation,
                now_ms,
            ):
                return self._decision(CommandStatus.REJECTED, "LEASE_VALIDATION_FAILED", command_id)

            if not self._reserve_replay(command.command_id):
                return self._decision(CommandStatus.REJECTED, "DUPLICATE_OR_REPLAYED_COMMAND", command_id)
        except Exception:
            return self._decision(CommandStatus.INDETERMINATE, "TRUST_SERVICE_FAILURE", command_id)

        try:
            latest_inhibit = self._inhibit.snapshot()
        except Exception:
            return self._decision(CommandStatus.INDETERMINATE, "INHIBIT_STATE_UNAVAILABLE", command_id)

        if latest_inhibit.latched or latest_inhibit.revision != initial_inhibit.revision:
            return self._decision(CommandStatus.REJECTED, "INHIBIT_CHANGED_DURING_VALIDATION", command_id)

        return self._decision(CommandStatus.ACCEPTED, "SIMULATION_COMMAND_ACCEPTED", command_id, permitted=True)
