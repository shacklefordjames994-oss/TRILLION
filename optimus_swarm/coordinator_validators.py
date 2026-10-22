from optimus_swarm.durable_coordinator import DurableCoordinator
from optimus_swarm.durable_models import DurableTaskStatus
from optimus_swarm.epoch_store import EpochStore


def epoch_is_current(store: EpochStore, coordinator_id: str, epoch: int) -> bool:
    current = store.current()
    return current is not None and current.coordinator_id == coordinator_id and current.epoch == epoch


def lease_is_current(
    coordinator: DurableCoordinator,
    *,
    task_id: str,
    worker_id: str,
    lease_id: str,
    generation: int,
    now_ms: int,
) -> bool:
    task = coordinator.get_task(task_id)
    if task is None or task.status != DurableTaskStatus.LEASED:
        return False
    if task.worker_id != worker_id or task.lease_id != lease_id or task.generation != generation:
        return False
    if task.lease_expires_at_ms is None or task.lease_expires_at_ms <= now_ms:
        return False
    return True
