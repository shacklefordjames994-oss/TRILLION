from optimus_swarm.recovery_controller import decide_recovery
from optimus_swarm.recovery_models import RecoveryReport, RecoveryStatus


def report(status):
    return RecoveryReport(
        status=status,
        checked_at_ms=100_000,
        issues=(),
        valid_lease_ids=(),
        expired_lease_ids=(),
        physical_execution_authorized=False,
    )


def test_indeterminate_never_continues():
    decision = decide_recovery(report(RecoveryStatus.INDETERMINATE), human_review_recorded=True)
    assert not decision.may_continue_simulation
    assert decision.require_human_review
    assert decision.physical_execution_authorized is False


def test_inhibited_never_continues():
    decision = decide_recovery(report(RecoveryStatus.INHIBITED), human_review_recorded=True)
    assert not decision.may_continue_simulation


def test_ready_requires_review_record():
    decision = decide_recovery(report(RecoveryStatus.READY), human_review_recorded=False)
    assert not decision.may_continue_simulation
    assert decision.reason == "RECOVERY_REVIEW_NOT_RECORDED"


def test_ready_with_review_allows_simulation_only():
    decision = decide_recovery(report(RecoveryStatus.READY), human_review_recorded=True)
    assert decision.may_continue_simulation
    assert not decision.physical_execution_authorized
    assert decision.reason == "SIMULATION_RECOVERY_APPROVED"
