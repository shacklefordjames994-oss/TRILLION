from optimus_swarm.task_coordinator import TaskCoordinator
from optimus_swarm.task_models import TaskStatus


def dispatch_pending(
    coordinator: TaskCoordinator,
    *,
    now_ms: int,
    lease_duration_ms: int,
    worker_ids: list[str],
) -> list[dict[str, str]]:
    if now_ms < 0:
        raise ValueError("now_ms must be non-negative")

    if lease_duration_ms <= 0:
        raise ValueError("lease_duration_ms must be positive")

    if len(worker_ids) != len(set(worker_ids)):
        raise ValueError("worker_ids must be unique")

    assignments: list[dict[str, str]] = []
    pending = sorted(
        (snapshot for snapshot in coordinator.list_snapshots() if snapshot.status == TaskStatus.PENDING),
        key=lambda snapshot: (-snapshot.task.priority, snapshot.task.task_id),
    )

    for snapshot in pending:
        for worker_id in sorted(worker_ids):
            decision = coordinator.assign(
                task_id=snapshot.task.task_id,
                worker_id=worker_id,
                now_ms=now_ms,
                lease_duration_ms=lease_duration_ms,
            )
            if not decision.accepted or decision.snapshot is None:
                continue

            lease = decision.snapshot.lease
            if lease is None:
                raise RuntimeError("Coordinator accepted assignment without a lease")

            assignments.append(
                {
                    "task_id": lease.task_id,
                    "worker_id": lease.worker_id,
                    "lease_id": lease.lease_id,
                    "generation": str(lease.generation),
                    "mode": "SIMULATION_ONLY",
                }
            )
            break

    return assignments
