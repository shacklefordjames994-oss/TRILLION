import hashlib

from optimus_swarm.coordinator_startup import initialize_coordinator
from optimus_swarm.durable_coordinator import DurableCoordinator
from optimus_swarm.durable_models import DurableTaskStatus
from optimus_swarm.epoch_guard import CoordinatorMessage, validate_coordinator_message
from optimus_swarm.epoch_store import EpochStore
from optimus_swarm.startup_recovery import StartupRecovery


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def test_epoch_increments_across_restarts(tmp_path):
    path = str(tmp_path / "coordinator.sqlite3")
    store = EpochStore(path)

    first = store.start_incarnation("coordinator-A", now_ms=1000)
    second = store.start_incarnation("coordinator-A", now_ms=2000)

    assert first.epoch == 1
    assert second.epoch == 2
    current = store.current()
    assert current is not None
    assert current.epoch == 2


def test_stale_epoch_message_rejected():
    message = CoordinatorMessage(
        coordinator_id="coordinator-A",
        epoch=2,
        message_id="msg-1",
        task_id="task-1",
        generation=3,
    )
    result = validate_coordinator_message(message, active_coordinator_id="coordinator-A", active_epoch=3)

    assert not result.accepted
    assert result.code == "STALE_COORDINATOR_EPOCH"
    assert result.physical_execution_authorized is False


def test_future_epoch_message_rejected():
    message = CoordinatorMessage(
        coordinator_id="coordinator-A",
        epoch=5,
        message_id="msg-2",
        task_id="task-1",
        generation=1,
    )
    result = validate_coordinator_message(message, active_coordinator_id="coordinator-A", active_epoch=4)

    assert not result.accepted
    assert result.code == "UNKNOWN_FUTURE_EPOCH"


def test_restart_recovery_invalidates_old_lease(tmp_path):
    path = str(tmp_path / "coordinator.sqlite3")
    coordinator = DurableCoordinator(path)
    coordinator.register_worker("robot-1")
    coordinator.submit("task-1", digest("payload"))
    assigned = coordinator.assign("task-1", "robot-1", now_ms=1000, lease_duration_ms=10000)
    assert assigned.accepted and assigned.task is not None

    epoch = EpochStore(path).start_incarnation("coordinator-A", now_ms=2000)
    recovery = StartupRecovery(path).recover(epoch=epoch.epoch, now_ms=2000, startup_authority_verified=True)

    assert recovery.status.value == "RECOVERY_REQUIRED"
    assert len(recovery.items) == 1
    assert recovery.physical_execution_authorized is False

    recovered_task = coordinator.get_task("task-1")
    assert recovered_task is not None
    assert recovered_task.status == DurableTaskStatus.PENDING
    assert recovered_task.lease_id is None
    assert recovered_task.generation > assigned.task.generation


def test_recovery_requires_startup_authorization(tmp_path):
    path = str(tmp_path / "coordinator.sqlite3")
    coordinator = DurableCoordinator(path)
    coordinator.submit("task-1", digest("payload"))

    recovery = StartupRecovery(path).recover(epoch=1, now_ms=1000, startup_authority_verified=False)

    assert recovery.status.value == "RECOVERY_REQUIRED"
    task = coordinator.get_task("task-1")
    assert task is not None
    assert task.status == DurableTaskStatus.PENDING


def test_recovery_never_authorizes_physical_execution(tmp_path):
    path = str(tmp_path / "coordinator.sqlite3")
    coordinator = DurableCoordinator(path)
    coordinator.submit("task-1", digest("payload"))

    recovery = StartupRecovery(path).recover(epoch=1, now_ms=1000, startup_authority_verified=True)

    assert recovery.status.value == "ACTIVE"
    assert recovery.physical_execution_authorized is False


def test_state_change_requires_current_epoch_after_startup(tmp_path):
    path = str(tmp_path / "coordinator.sqlite3")
    coordinator = DurableCoordinator(path)
    coordinator.register_worker("robot-1")
    coordinator.submit("task-1", digest("payload"))
    assigned = coordinator.assign("task-1", "robot-1", now_ms=1000, lease_duration_ms=10000)
    assert assigned.task is not None and assigned.task.lease_id is not None

    EpochStore(path).start_incarnation("coordinator-A", now_ms=2000)
    missing = coordinator.complete(
        "task-1",
        "robot-1",
        generation=assigned.task.generation,
        lease_id=assigned.task.lease_id,
        completion_key="complete-1",
        result_digest=digest("done"),
        now_ms=2100,
    )
    stale = coordinator.complete(
        "task-1",
        "robot-1",
        generation=assigned.task.generation,
        lease_id=assigned.task.lease_id,
        completion_key="complete-1",
        result_digest=digest("done"),
        now_ms=2100,
        claimed_coordinator_id="coordinator-A",
        claimed_epoch=0,
        message_id="msg-stale",
    )
    current = coordinator.complete(
        "task-1",
        "robot-1",
        generation=assigned.task.generation,
        lease_id=assigned.task.lease_id,
        completion_key="complete-1",
        result_digest=digest("done"),
        now_ms=2200,
        claimed_coordinator_id="coordinator-A",
        claimed_epoch=1,
        message_id="msg-current",
    )

    assert missing.code == "EPOCH_REQUIRED"
    assert stale.code == "INVALID_MESSAGE"
    assert current.accepted
    assert current.code == "TASK_COMPLETED"
    assert current.physical_execution_authorized is False
    assert coordinator.get_task("task-1").status == DurableTaskStatus.COMPLETED


def test_recovered_lease_does_not_announce_readiness(tmp_path):
    path = str(tmp_path / "coordinator.sqlite3")
    coordinator = DurableCoordinator(path)
    coordinator.register_worker("robot-1")
    coordinator.submit("task-1", digest("payload"))
    coordinator.assign("task-1", "robot-1", now_ms=1000, lease_duration_ms=10000)

    started = initialize_coordinator(
        path,
        coordinator_id="coordinator-A",
        now_ms=2000,
        startup_authority_verified=True,
    )

    assert started["ready"] is False
    assert started["physical_execution_authorized"] is False
    assert started["recovery"].status.value == "RECOVERY_REQUIRED"
