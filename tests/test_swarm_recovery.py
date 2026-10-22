import hashlib

from optimus_swarm.command_gateway import CommandGateway
from optimus_swarm.command_models import CommandEnvelope, CommandStatus, EvidenceClass
from optimus_swarm.command_policy import payload_digest
from optimus_swarm.durable_coordinator import DurableCoordinator
from optimus_swarm.durable_models import DurableTaskStatus
from optimus_swarm.inhibit_state import InhibitState
from optimus_swarm.recovery_models import ActiveLeaseRecord, RecoveryStatus, WorkerHeartbeat
from optimus_swarm.swarm_recovery import recover_swarm

NOW = 100_000


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def heartbeat(worker_id: str) -> WorkerHeartbeat:
    return WorkerHeartbeat(worker_id=worker_id, observed_at_ms=NOW - 1_000, sequence=4, healthy=True)


def lease(worker_id: str = "robot-1", lease_id: str = "lease-1") -> ActiveLeaseRecord:
    return ActiveLeaseRecord(
        lease_id=lease_id,
        task_id="task-1",
        worker_id=worker_id,
        generation=1,
        issued_at_ms=NOW - 5_000,
        expires_at_ms=NOW + 10_000,
    )


def leased_database(tmp_path):
    path = str(tmp_path / "swarm.sqlite3")
    coordinator = DurableCoordinator(path)
    coordinator.register_worker("robot-1")
    coordinator.submit("task-1", digest("payload"))
    assigned = coordinator.assign("task-1", "robot-1", now_ms=NOW - 5_000, lease_duration_ms=20_000)
    assert assigned.accepted
    return coordinator, path


def test_recovery_latches_inhibit_and_does_not_resume(tmp_path):
    coordinator, path = leased_database(tmp_path)
    inhibit = InhibitState(lambda actor, approval: False)
    result = recover_swarm(
        now_ms=NOW,
        inhibit=inhibit,
        known_worker_ids={"robot-1", "robot-2"},
        known_task_ids={"task-1"},
        leases=[lease()],
        heartbeats=[heartbeat("robot-1"), heartbeat("robot-2")],
        database_path=path,
        startup_authority_verified=True,
        human_review_recorded=True,
    )
    task = coordinator.get_task("task-1")

    assert result.inhibit_latched
    assert inhibit.snapshot().latched
    assert result.simulation_resumed is False
    assert result.physical_execution_authorized is False
    assert result.reason == "LEASES_FENCED_NOT_RESUMED"
    assert result.recovered_task_ids == ("task-1",)
    assert task is not None
    assert task.status == DurableTaskStatus.PENDING
    assert task.lease_id is None


def test_conflicting_ownership_is_not_rewritten(tmp_path):
    coordinator, path = leased_database(tmp_path)
    before = coordinator.get_task("task-1")
    assert before is not None
    result = recover_swarm(
        now_ms=NOW,
        inhibit=InhibitState(lambda actor, approval: False),
        known_worker_ids={"robot-1", "robot-2"},
        known_task_ids={"task-1", "task-2"},
        leases=[lease(lease_id="lease-a"), lease(worker_id="robot-2", lease_id="lease-b")],
        heartbeats=[heartbeat("robot-1"), heartbeat("robot-2")],
        database_path=path,
        startup_authority_verified=True,
        human_review_recorded=True,
    )
    after = coordinator.get_task("task-1")

    assert result.status == RecoveryStatus.INDETERMINATE
    assert result.reason == "OWNERSHIP_NOT_REWRITTEN"
    assert result.tasks_rewritten is False
    assert result.simulation_resumed is False
    assert after is not None
    assert after.status == DurableTaskStatus.LEASED
    assert after.lease_id == before.lease_id
    assert after.generation == before.generation


def test_gateway_rejects_commands_after_recovery(tmp_path):
    _, path = leased_database(tmp_path)
    inhibit = InhibitState(lambda actor, approval: False)
    recover_swarm(
        now_ms=NOW,
        inhibit=inhibit,
        known_worker_ids={"robot-1"},
        known_task_ids={"task-1"},
        leases=[lease()],
        heartbeats=[heartbeat("robot-1")],
        database_path=path,
        startup_authority_verified=True,
    )
    payload = {"action": "navigate_simulated", "target": "zone-A"}
    gateway = CommandGateway(
        coordinator_id="coordinator-A",
        current_epoch=1,
        inhibit_state=inhibit,
        epoch_validator=lambda coordinator, epoch: True,
        lease_validator=lambda *args: True,
        replay_reserver=lambda command_id: True,
    )
    decision = gateway.authorize_simulation(
        CommandEnvelope(
            command_id="command-after-recovery",
            coordinator_id="coordinator-A",
            coordinator_epoch=1,
            task_id="task-1",
            worker_id="robot-1",
            lease_id="lease-1",
            generation=1,
            issued_at_ms=NOW - 100,
            expires_at_ms=NOW + 5_000,
            evidence_class=EvidenceClass.SIMULATED,
            payload=payload,
            payload_digest=payload_digest(payload),
            signature_verified=True,
        ),
        now_ms=NOW,
    )

    assert decision.status == CommandStatus.REJECTED
    assert decision.code == "SYSTEM_INHIBITED"
    assert decision.physical_execution_authorized is False


def test_inhibit_failure_does_not_rewrite_tasks(tmp_path):
    coordinator, path = leased_database(tmp_path)
    before = coordinator.get_task("task-1")

    class BrokenInhibit:
        def engage(self, **kwargs):
            raise RuntimeError("inhibit unavailable")

        def snapshot(self):
            raise RuntimeError("inhibit unavailable")

    result = recover_swarm(
        now_ms=NOW,
        inhibit=BrokenInhibit(),
        known_worker_ids={"robot-1"},
        known_task_ids={"task-1"},
        leases=[lease()],
        heartbeats=[heartbeat("robot-1")],
        database_path=path,
        startup_authority_verified=True,
    )
    after = coordinator.get_task("task-1")

    assert result.status == RecoveryStatus.INDETERMINATE
    assert result.reason == "INHIBIT_ENGAGE_FAILED"
    assert result.tasks_rewritten is False
    assert result.simulation_resumed is False
    assert after.lease_id == before.lease_id
