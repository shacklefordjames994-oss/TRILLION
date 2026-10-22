from optimus_swarm.epoch_store import EpochStore
from optimus_swarm.startup_recovery import StartupRecovery


def initialize_coordinator(
    database_path: str,
    *,
    coordinator_id: str,
    now_ms: int,
    startup_authority_verified: bool,
):
    """
    Order only. This is not an exclusive multi-host lock.

    A recovered lease returns RECOVERY_REQUIRED, so the coordinator
    does not announce readiness or resume work.
    """
    incarnation = EpochStore(database_path).start_incarnation(coordinator_id, now_ms=now_ms)
    recovery = StartupRecovery(database_path).recover(
        epoch=incarnation.epoch,
        now_ms=now_ms,
        startup_authority_verified=startup_authority_verified,
    )
    return {
        "ready": recovery.status.value == "ACTIVE",
        "coordinator_id": coordinator_id,
        "epoch": incarnation.epoch,
        "recovery": recovery,
        "physical_execution_authorized": False,
    }
