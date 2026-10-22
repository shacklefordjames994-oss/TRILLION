from dataclasses import dataclass

from optimus_swarm.recovery_models import RecoveryReport, RecoveryStatus


@dataclass(frozen=True)
class RecoveryDecision:
    may_continue_simulation: bool
    require_human_review: bool
    rejected_lease_ids: tuple[str, ...]
    reason: str
    physical_execution_authorized: bool = False


def decide_recovery(report: RecoveryReport, *, human_review_recorded: bool = False) -> RecoveryDecision:
    if report.physical_execution_authorized:
        return RecoveryDecision(
            may_continue_simulation=False,
            require_human_review=True,
            rejected_lease_ids=report.valid_lease_ids,
            reason="INVALID_REPORT_PHYSICAL_AUTHORIZATION",
        )

    if report.status == RecoveryStatus.INDETERMINATE:
        return RecoveryDecision(
            may_continue_simulation=False,
            require_human_review=True,
            rejected_lease_ids=report.valid_lease_ids,
            reason="AUTHORITATIVE_STATE_UNCERTAIN",
        )

    if report.status == RecoveryStatus.INHIBITED:
        return RecoveryDecision(
            may_continue_simulation=False,
            require_human_review=True,
            rejected_lease_ids=report.expired_lease_ids,
            reason="RECOVERY_CHECKS_FAILED",
        )

    if not human_review_recorded:
        return RecoveryDecision(
            may_continue_simulation=False,
            require_human_review=True,
            rejected_lease_ids=(),
            reason="RECOVERY_REVIEW_NOT_RECORDED",
        )

    return RecoveryDecision(
        may_continue_simulation=True,
        require_human_review=False,
        rejected_lease_ids=(),
        reason="SIMULATION_RECOVERY_APPROVED",
    )
