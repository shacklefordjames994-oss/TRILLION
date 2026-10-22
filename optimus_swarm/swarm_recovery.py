from dataclasses import dataclass
from typing import Iterable

from optimus_swarm.epoch_store import EpochStore
from optimus_swarm.inhibit_state import InhibitState
from optimus_swarm.reconciliation import reconcile_swarm
from optimus_swarm.recovery_controller import decide_recovery
from optimus_swarm.recovery_models import ActiveLeaseRecord, RecoveryStatus, WorkerHeartbeat
from optimus_swarm.startup_recovery import StartupRecovery


@dataclass(frozen=True)
class SwarmRecoveryResult:
    status: RecoveryStatus
    reason: str
    inhibit_latched: bool
    recovered_task_ids: tuple[str, ...]
    tasks_rewritten: bool
    simulation_resumed: bool
    physical_execution_authorized: bool = False


def recover_swarm(
    *,
    now_ms: int,
    inhibit: InhibitState,
    known_worker_ids: set[str],
    known_task_ids: set[str],
    leases: Iterable[ActiveLeaseRecord],
    heartbeats: Iterable[WorkerHeartbeat],
    database_path: str | None = None,
    coordinator_id: str = "coordinator-A",
    startup_authority_verified: bool = False,
    human_review_recorded: bool = False,
) -> SwarmRecoveryResult:
    """
    Latch first, then classify. Do not resume work.

    human_review_recorded is accepted and ignored. A review flag is not
    authorization to clear the inhibit or dispatch a task. Conflicting
    ownership is not rewritten.
    """
    del human_review_recorded

    try:
        snapshot = inhibit.engage(reason="SWARM_RECOVERY", now_ms=now_ms)
    except Exception:
        return SwarmRecoveryResult(
            status=RecoveryStatus.INDETERMINATE,
            reason="INHIBIT_ENGAGE_FAILED",
            inhibit_latched=False,
            recovered_task_ids=(),
            tasks_rewritten=False,
            simulation_resumed=False,
        )

    if not snapshot.latched:
        return SwarmRecoveryResult(
            status=RecoveryStatus.INDETERMINATE,
            reason="INHIBIT_DID_NOT_LATCH",
            inhibit_latched=False,
            recovered_task_ids=(),
            tasks_rewritten=False,
            simulation_resumed=False,
        )

    try:
        report = reconcile_swarm(
            now_ms=now_ms,
            known_worker_ids=known_worker_ids,
            known_task_ids=known_task_ids,
            leases=leases,
            heartbeats=heartbeats,
        )
    except Exception:
        return SwarmRecoveryResult(
            status=RecoveryStatus.INDETERMINATE,
            reason="RECONCILIATION_FAILED",
            inhibit_latched=True,
            recovered_task_ids=(),
            tasks_rewritten=False,
            simulation_resumed=False,
        )

    # Never pass the review flag through. Recovery cannot resume simulation.
    decide_recovery(report, human_review_recorded=False)

    if report.status == RecoveryStatus.INDETERMINATE or not database_path or not startup_authority_verified:
        reason = "OWNERSHIP_NOT_REWRITTEN" if report.status == RecoveryStatus.INDETERMINATE else "RECOVERY_HELD"
        return SwarmRecoveryResult(
            status=report.status,
            reason=reason,
            inhibit_latched=True,
            recovered_task_ids=(),
            tasks_rewritten=False,
            simulation_resumed=False,
        )

    try:
        incarnation = EpochStore(database_path).start_incarnation(coordinator_id, now_ms=now_ms)
        recovery = StartupRecovery(database_path).recover(
            epoch=incarnation.epoch,
            now_ms=now_ms,
            startup_authority_verified=True,
        )
    except Exception:
        return SwarmRecoveryResult(
            status=RecoveryStatus.INDETERMINATE,
            reason="LEASE_FENCE_FAILED",
            inhibit_latched=True,
            recovered_task_ids=(),
            tasks_rewritten=False,
            simulation_resumed=False,
        )

    return SwarmRecoveryResult(
        status=report.status,
        reason="LEASES_FENCED_NOT_RESUMED",
        inhibit_latched=inhibit.snapshot().latched,
        recovered_task_ids=tuple(item.task_id for item in recovery.items),
        tasks_rewritten=bool(recovery.items),
        simulation_resumed=False,
    )
