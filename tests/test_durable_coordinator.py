import hashlib

from optimus_swarm.durable_coordinator import DurableCoordinator
from optimus_swarm.durable_models import DurableTaskStatus


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def setup_coordinator(tmp_path):
    db_path = str(tmp_path / "swarm.sqlite3")
    coordinator = DurableCoordinator(db_path)
    assert coordinator.register_worker("robot-1").accepted
    assert coordinator.register_worker("robot-2").accepted
    assert coordinator.submit("task-1", digest("payload-1"), priority=5).accepted
    return coordinator, db_path


def test_submit_rejects_duplicate_task(tmp_path):
    coordinator, _ = setup_coordinator(tmp_path)
    result = coordinator.submit("task-1", digest("other"))
    assert not result.accepted
    assert result.code == "DUPLICATE_TASK_ID"
    assert result.physical_execution_authorized is False


def test_assign_creates_generation_one_lease(tmp_path):
    coordinator, _ = setup_coordinator(tmp_path)
    result = coordinator.assign("task-1", "robot-1", now_ms=1000, lease_duration_ms=5000)

    assert result.accepted
    assert result.task is not None
    assert result.task.generation == 1
    assert result.task.status == DurableTaskStatus.LEASED
    assert result.task.worker_id == "robot-1"
    assert result.physical_execution_authorized is False


def test_active_lease_cannot_be_reassigned(tmp_path):
    coordinator, _ = setup_coordinator(tmp_path)
    coordinator.assign("task-1", "robot-1", now_ms=1000, lease_duration_ms=5000)
    result = coordinator.assign("task-1", "robot-2", now_ms=2000, lease_duration_ms=5000)

    assert not result.accepted
    assert result.code == "TASK_ALREADY_LEASED"


def test_expired_lease_increments_fencing_token(tmp_path):
    coordinator, _ = setup_coordinator(tmp_path)
    first = coordinator.assign("task-1", "robot-1", now_ms=1000, lease_duration_ms=500)
    second = coordinator.assign("task-1", "robot-2", now_ms=1500, lease_duration_ms=5000)

    assert first.task is not None and second.task is not None
    assert second.accepted
    assert second.task.generation == 2
    assert second.task.worker_id == "robot-2"
    assert second.task.lease_id != first.task.lease_id


def test_stale_worker_cannot_complete_newer_lease(tmp_path):
    coordinator, _ = setup_coordinator(tmp_path)
    first = coordinator.assign("task-1", "robot-1", now_ms=1000, lease_duration_ms=500)
    coordinator.assign("task-1", "robot-2", now_ms=1500, lease_duration_ms=5000)
    assert first.task is not None

    stale = coordinator.complete(
        "task-1",
        "robot-1",
        generation=1,
        lease_id=first.task.lease_id or "",
        completion_key="complete-old",
        result_digest=digest("old"),
        now_ms=1600,
    )

    assert not stale.accepted
    assert stale.code == "STALE_FENCING_TOKEN"
    assert stale.physical_execution_authorized is False


def test_completion_replay_is_idempotent(tmp_path):
    coordinator, _ = setup_coordinator(tmp_path)
    granted = coordinator.assign("task-1", "robot-1", now_ms=1000, lease_duration_ms=5000)
    assert granted.task is not None and granted.task.lease_id is not None

    first = coordinator.complete(
        "task-1",
        "robot-1",
        generation=granted.task.generation,
        lease_id=granted.task.lease_id,
        completion_key="complete-1",
        result_digest=digest("done"),
        now_ms=1200,
    )
    second = coordinator.complete(
        "task-1",
        "robot-1",
        generation=granted.task.generation,
        lease_id=granted.task.lease_id,
        completion_key="complete-1",
        result_digest=digest("done"),
        now_ms=1300,
    )

    assert first.accepted and first.code == "TASK_COMPLETED"
    assert second.accepted and second.code == "IDEMPOTENT_REPLAY"
    assert second.task is not None
    assert second.task.status == DurableTaskStatus.COMPLETED


def test_conflicting_completion_is_rejected(tmp_path):
    coordinator, _ = setup_coordinator(tmp_path)
    granted = coordinator.assign("task-1", "robot-1", now_ms=1000, lease_duration_ms=5000)
    assert granted.task is not None and granted.task.lease_id is not None
    coordinator.complete(
        "task-1",
        "robot-1",
        generation=1,
        lease_id=granted.task.lease_id,
        completion_key="complete-1",
        result_digest=digest("done"),
        now_ms=1200,
    )
    conflict = coordinator.complete(
        "task-1",
        "robot-1",
        generation=1,
        lease_id=granted.task.lease_id,
        completion_key="complete-other",
        result_digest=digest("other"),
        now_ms=1300,
    )

    assert not conflict.accepted
    assert conflict.code == "CONFLICTING_COMPLETION"


def test_lease_survives_coordinator_restart(tmp_path):
    coordinator, path = setup_coordinator(tmp_path)
    granted = coordinator.assign("task-1", "robot-1", now_ms=1000, lease_duration_ms=5000)
    assert granted.task is not None

    reopened = DurableCoordinator(path)
    task = reopened.get_task("task-1")

    assert task is not None
    assert task.status == DurableTaskStatus.LEASED
    assert task.generation == granted.task.generation
    assert task.lease_id == granted.task.lease_id
    assert task.worker_id == "robot-1"


def test_cancel_without_authorization_does_not_clear_lease(tmp_path):
    coordinator, _ = setup_coordinator(tmp_path)
    coordinator.assign("task-1", "robot-1", now_ms=1000, lease_duration_ms=5000)
    denied = coordinator.cancel("task-1", now_ms=1100, authorization_verified=False)
    task = coordinator.get_task("task-1")

    assert denied.code == "AUTHORIZATION_REQUIRED"
    assert task is not None
    assert task.status == DurableTaskStatus.LEASED
