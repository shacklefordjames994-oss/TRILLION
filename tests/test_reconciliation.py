from optimus_swarm.reconciliation import reconcile_swarm
from optimus_swarm.recovery_models import ActiveLeaseRecord, RecoveryStatus, WorkerHeartbeat

NOW = 100_000


def heartbeat(worker_id="robot-1", *, healthy=True, sequence=4):
    return WorkerHeartbeat(
        worker_id=worker_id,
        observed_at_ms=NOW - 1_000,
        sequence=sequence,
        healthy=healthy,
    )


def lease(
    *,
    lease_id="lease-1",
    task_id="task-1",
    worker_id="robot-1",
    generation=1,
    issued_at_ms=NOW - 5_000,
    expires_at_ms=NOW + 10_000,
):
    return ActiveLeaseRecord(
        lease_id=lease_id,
        task_id=task_id,
        worker_id=worker_id,
        generation=generation,
        issued_at_ms=issued_at_ms,
        expires_at_ms=expires_at_ms,
    )


def run_check(leases=None, heartbeats=None, **kwargs):
    return reconcile_swarm(
        now_ms=NOW,
        known_worker_ids={"robot-1", "robot-2"},
        known_task_ids={"task-1", "task-2"},
        leases=leases or [],
        heartbeats=heartbeats if heartbeats is not None else [heartbeat("robot-1"), heartbeat("robot-2")],
        **kwargs,
    )


def test_clean_snapshot_is_ready():
    report = run_check(leases=[lease()])
    assert report.status == RecoveryStatus.READY
    assert report.physical_execution_authorized is False


def test_expired_lease_inhibits_recovery():
    report = run_check(leases=[lease(expires_at_ms=NOW - 1)])
    assert report.status == RecoveryStatus.INHIBITED
    assert report.expired_lease_ids == ("lease-1",)


def test_duplicate_task_ownership_is_indeterminate():
    report = run_check(
        leases=[
            lease(lease_id="lease-a"),
            lease(lease_id="lease-b", worker_id="robot-2"),
        ]
    )
    assert report.status == RecoveryStatus.INDETERMINATE
    assert any(item.code == "MULTIPLE_TASK_OWNERS" for item in report.issues)


def test_unknown_worker_is_indeterminate():
    report = run_check(leases=[lease(worker_id="robot-unknown")])
    assert report.status == RecoveryStatus.INDETERMINATE


def test_missing_heartbeat_inhibits_recovery():
    report = run_check(heartbeats=[heartbeat("robot-1")])
    assert report.status == RecoveryStatus.INHIBITED


def test_unhealthy_worker_inhibits_recovery():
    report = run_check(heartbeats=[heartbeat("robot-1", healthy=False), heartbeat("robot-2")])
    assert report.status == RecoveryStatus.INHIBITED


def test_future_heartbeat_is_indeterminate():
    future = WorkerHeartbeat(worker_id="robot-1", observed_at_ms=NOW + 10_000, sequence=5, healthy=True)
    report = run_check(heartbeats=[future, heartbeat("robot-2")])
    assert report.status == RecoveryStatus.INDETERMINATE


def test_duplicate_lease_id_is_indeterminate():
    report = run_check(
        leases=[
            lease(lease_id="duplicate"),
            lease(lease_id="duplicate", task_id="task-2", worker_id="robot-2"),
        ]
    )
    assert report.status == RecoveryStatus.INDETERMINATE


def test_physical_execution_never_authorized():
    report = run_check(leases=[lease()])
    assert report.physical_execution_authorized is False
