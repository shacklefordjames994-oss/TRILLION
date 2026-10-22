from dataclasses import dataclass

from optimus_swarm.epoch_models import EpochDecision


@dataclass(frozen=True)
class CoordinatorMessage:
    coordinator_id: str
    epoch: int
    message_id: str
    task_id: str
    generation: int


def validate_coordinator_message(
    message: CoordinatorMessage,
    *,
    active_coordinator_id: str,
    active_epoch: int,
) -> EpochDecision:
    if (
        not message.coordinator_id
        or not message.message_id
        or not message.task_id
        or message.epoch < 1
        or message.generation < 1
    ):
        return EpochDecision(False, "INVALID_MESSAGE", active_epoch)

    if message.coordinator_id != active_coordinator_id:
        return EpochDecision(False, "COORDINATOR_ID_MISMATCH", active_epoch)

    if message.epoch < active_epoch:
        return EpochDecision(False, "STALE_COORDINATOR_EPOCH", active_epoch)

    if message.epoch > active_epoch:
        return EpochDecision(False, "UNKNOWN_FUTURE_EPOCH", active_epoch)

    return EpochDecision(True, "MESSAGE_EPOCH_VALID", active_epoch, physical_execution_authorized=False)
