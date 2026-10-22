from dataclasses import dataclass

from optimus_swarm.task_models import TaskLease


@dataclass(frozen=True)
class AdmissionDecision:
    accepted: bool
    reason: str
    physical_execution_authorized: bool = False


def admit_simulated_task(
    lease: TaskLease,
    *,
    worker_id: str,
    now_ms: int,
    kill_switch,
    integrity_verified: bool,
) -> AdmissionDecision:
    """
    Gate a simulated task only.

    kill_switch must expose a state object with a latched attribute.
    This gate does not control hardware or clear the safety latch.
    """
    if not integrity_verified:
        return AdmissionDecision(False, "INTEGRITY_NOT_VERIFIED")

    if not worker_id or worker_id != lease.worker_id:
        return AdmissionDecision(False, "WORKER_IDENTITY_MISMATCH")

    if now_ms < lease.issued_at_ms:
        return AdmissionDecision(False, "INVALID_CURRENT_TIME")

    if now_ms >= lease.expires_at_ms:
        return AdmissionDecision(False, "LEASE_EXPIRED")

    state = getattr(kill_switch, "state", None)
    if state is None or not hasattr(state, "latched"):
        return AdmissionDecision(False, "SAFETY_STATE_UNAVAILABLE")

    if state.latched:
        return AdmissionDecision(False, "SAFETY_INHIBIT_ACTIVE")

    return AdmissionDecision(
        accepted=True,
        reason="SIMULATED_TASK_ADMITTED",
        physical_execution_authorized=False,
    )
