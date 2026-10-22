from optimus_swarm.task_coordinator import TaskCoordinator
from optimus_swarm.task_models import TaskSpec, TaskStatus, WorkerStatus
from optimus_swarm.task_scheduler import dispatch_pending


def make_task(task_id="task-001", priority=1):
    return TaskSpec(
        task_id=task_id,
        task_type="SIMULATED_LOCALIZATION",
        payload_digest="sha256:synthetic-test-payload",
        priority=priority,
    )


def setup_coordinator():
    coordinator = TaskCoordinator({"robot-001", "robot-002"})
    result = coordinator.submit(make_task())
    assert result.accepted
    return coordinator


def test_duplicate_task_submission_is_rejected():
    coordinator = setup_coordinator()
    result = coordinator.submit(make_task())

    assert not result.accepted
    assert result.reason == "DUPLICATE_TASK_ID"


def test_only_one_worker_receives_initial_lease():
    coordinator = setup_coordinator()

    first = coordinator.assign("task-001", "robot-001", now_ms=1000, lease_duration_ms=1000)
    second = coordinator.assign("task-001", "robot-002", now_ms=1000, lease_duration_ms=1000)

    assert first.accepted
    assert first.physical_execution_authorized is False
    assert not second.accepted
    assert second.reason == "TASK_NOT_PENDING"


def test_lease_expires_and_can_be_reassigned():
    coordinator = setup_coordinator()

    first = coordinator.assign("task-001", "robot-001", now_ms=1000, lease_duration_ms=1000)
    assert first.accepted

    second = coordinator.assign("task-001", "robot-002", now_ms=2000, lease_duration_ms=1000)

    assert second.accepted
    assert second.snapshot is not None
    assert second.snapshot.lease is not None
    assert second.snapshot.lease.worker_id == "robot-002"
    assert second.snapshot.generation == 2


def test_expired_worker_cannot_complete_task():
    coordinator = setup_coordinator()
    assigned = coordinator.assign("task-001", "robot-001", now_ms=1000, lease_duration_ms=100)
    assert assigned.snapshot is not None and assigned.snapshot.lease is not None
    lease = assigned.snapshot.lease

    result = coordinator.complete("task-001", "robot-001", lease.lease_id, now_ms=1100)

    assert not result.accepted
    assert result.reason in {"NO_ACTIVE_LEASE", "LEASE_EXPIRED"}


def test_worker_cannot_complete_another_workers_lease():
    coordinator = setup_coordinator()
    assigned = coordinator.assign("task-001", "robot-001", now_ms=1000, lease_duration_ms=1000)
    assert assigned.snapshot is not None and assigned.snapshot.lease is not None
    lease = assigned.snapshot.lease

    result = coordinator.complete("task-001", "robot-002", lease.lease_id, now_ms=1100)

    assert not result.accepted
    assert result.reason == "LEASE_IDENTITY_MISMATCH"


def test_human_authority_required_for_cancellation():
    coordinator = setup_coordinator()
    result = coordinator.cancel("task-001", authorized_human=False, reason="Cancel for review")

    assert not result.accepted
    assert result.reason == "HUMAN_AUTHORITY_REQUIRED"


def test_authorized_cancellation_releases_worker():
    coordinator = setup_coordinator()
    assigned = coordinator.assign("task-001", "robot-001", now_ms=1000, lease_duration_ms=1000)
    assert assigned.accepted

    result = coordinator.cancel(
        "task-001",
        authorized_human=True,
        reason="Human operator cancelled simulated task",
    )

    assert result.accepted
    assert result.snapshot is not None
    assert result.snapshot.status == TaskStatus.CANCELLED

    reassignment = coordinator.submit(make_task("task-002"))
    assert reassignment.accepted

    next_lease = coordinator.assign("task-002", "robot-001", now_ms=1100, lease_duration_ms=1000)
    assert next_lease.accepted


def test_unavailable_worker_cannot_be_assigned():
    coordinator = setup_coordinator()
    coordinator.set_worker_status("robot-002", WorkerStatus.UNAVAILABLE)

    result = coordinator.assign("task-001", "robot-002", now_ms=1000, lease_duration_ms=1000)

    assert not result.accepted
    assert result.reason == "WORKER_NOT_AVAILABLE"


def test_dispatch_prefers_higher_priority_then_task_id():
    coordinator = TaskCoordinator({"robot-001", "robot-002"})
    coordinator.submit(make_task("b-task", priority=1))
    coordinator.submit(make_task("a-task", priority=1))
    coordinator.submit(make_task("z-task", priority=5))

    results = dispatch_pending(
        coordinator,
        now_ms=1000,
        lease_duration_ms=500,
        worker_ids=["robot-002", "robot-001"],
    )

    assert [row["task_id"] for row in results] == ["z-task", "a-task"]
    assert results[0]["worker_id"] == "robot-001"
    assert results[0]["mode"] == "SIMULATION_ONLY"
    assert results[0]["generation"] == "1"
    assert coordinator.get_snapshot("b-task").status == TaskStatus.PENDING
