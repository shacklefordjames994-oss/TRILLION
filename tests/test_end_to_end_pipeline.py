import dataclasses
import hashlib

from optimus_swarm.command_crypto import generate_keypair, sign_command
from optimus_swarm.coordinator_validators import epoch_is_current, lease_is_current
from optimus_swarm.durable_coordinator import DurableCoordinator
from optimus_swarm.durable_models import DurableTaskStatus
from optimus_swarm.durable_replay_store import DurableReplayStore
from optimus_swarm.durable_simulation_store import DurableSimulationStore
from optimus_swarm.epoch_store import EpochStore
from optimus_swarm.inhibit_state import InhibitState
from optimus_swarm.integration_models import PipelineStatus
from optimus_swarm.integration_pipeline import OmegaSimulationPipeline
from optimus_swarm.key_registry import KeyRegistry, TrustedKey
from optimus_swarm.secure_command_gateway import SecureCommandGateway

NOW = 100_000


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def build(tmp_path, *, latched=False):
    db = str(tmp_path / "coordinator.sqlite3")
    coordinator = DurableCoordinator(db)
    coordinator.register_worker("robot-1")
    coordinator.submit("task-1", digest("payload"))
    assigned = coordinator.assign("task-1", "robot-1", now_ms=NOW - 1_000, lease_duration_ms=10_000)
    assert assigned.task is not None and assigned.task.lease_id is not None
    epoch = EpochStore(db).start_incarnation("coordinator-A", now_ms=NOW - 500)
    private_bytes, public_bytes = generate_keypair()
    inhibit = InhibitState(lambda actor, approval: actor == "human-1" and approval == "approval-1")
    if not latched:
        inhibit.reset(actor_id="human-1", authorization_id="approval-1", reason="test session", now_ms=NOW)
    gateway = SecureCommandGateway(
        coordinator_id="coordinator-A",
        key_registry=KeyRegistry([TrustedKey("key-v1", "operator-1", public_bytes)]),
        replay_store=DurableReplayStore(str(tmp_path / "replay.sqlite3")),
        inhibit_snapshot=lambda: (inhibit.snapshot().latched, inhibit.snapshot().revision),
        epoch_is_current=lambda coordinator_id, claimed: epoch_is_current(EpochStore(db), coordinator_id, claimed),
        lease_is_current=lambda **kwargs: lease_is_current(coordinator, **kwargs),
    )
    store = DurableSimulationStore(str(tmp_path / "events.sqlite3"))
    pipeline = OmegaSimulationPipeline(gateway=gateway, adapter=store)
    return pipeline, coordinator, assigned.task, private_bytes, epoch.epoch, inhibit, store, gateway


def command_for(private_bytes, task, epoch, **overrides):
    fields = {
        "private_key_bytes": private_bytes,
        "command_id": "command-e2e",
        "source_id": "operator-1",
        "key_id": "key-v1",
        "coordinator_id": "coordinator-A",
        "coordinator_epoch": epoch,
        "task_id": task.task_id,
        "worker_id": task.worker_id,
        "lease_id": task.lease_id,
        "generation": task.generation,
        "issued_at_ms": NOW - 100,
        "expires_at_ms": NOW + 5_000,
        "payload": {"operation": "simulate_navigation", "target": "zone-A"},
    }
    fields.update(overrides)
    return sign_command(**fields)


def test_signed_command_records_one_durable_event(tmp_path):
    pipeline, _, task, private_bytes, epoch, _, store, _ = build(tmp_path)
    result = pipeline.process(command_for(private_bytes, task, epoch), now_ms=NOW)
    reopened = DurableSimulationStore(store.database_path)

    assert result.status == PipelineStatus.ACCEPTED
    assert result.simulation_event_recorded is True
    assert result.physical_execution_authorized is False
    assert len(reopened.events()) == 1
    assert reopened.events()[0].mode == "SIMULATION_ONLY"


def test_inhibit_blocks_admission_and_records_no_event(tmp_path):
    pipeline, _, task, private_bytes, epoch, _, store, _ = build(tmp_path, latched=True)
    result = pipeline.process(command_for(private_bytes, task, epoch), now_ms=NOW)

    assert result.status == PipelineStatus.REJECTED
    assert result.stage == "SECURITY_GATEWAY"
    assert result.reason == "INHIBIT_LATCHED"
    assert store.events() == ()


def test_stale_epoch_and_expired_lease_are_rejected(tmp_path):
    pipeline, coordinator, task, private_bytes, epoch, _, store, _ = build(tmp_path)
    stale = pipeline.process(
        command_for(private_bytes, task, epoch, coordinator_epoch=epoch - 1, command_id="stale"),
        now_ms=NOW,
    )
    expired = pipeline.process(
        command_for(
            private_bytes,
            task,
            epoch,
            command_id="expired",
            expires_at_ms=task.lease_expires_at_ms + 5_000,
        ),
        now_ms=task.lease_expires_at_ms + 1,
    )

    assert stale.reason == "STALE_OR_UNKNOWN_EPOCH"
    assert expired.reason == "LEASE_NOT_CURRENT"
    assert store.events() == ()
    assert coordinator.get_task("task-1").status == DurableTaskStatus.LEASED


def test_duplicate_command_stays_rejected_after_restart(tmp_path):
    pipeline, _, task, private_bytes, epoch, _, store, gateway = build(tmp_path)
    command = command_for(private_bytes, task, epoch)
    first = pipeline.process(command, now_ms=NOW)
    gateway.replay_store = DurableReplayStore(gateway.replay_store.database_path)
    second = pipeline.process(command, now_ms=NOW)

    assert first.status == PipelineStatus.ACCEPTED
    assert second.reason == "DUPLICATE_COMMAND"
    assert len(store.events()) == 1


def test_unknown_key_is_rejected(tmp_path):
    pipeline, _, task, private_bytes, epoch, _, store, _ = build(tmp_path)
    result = pipeline.process(command_for(private_bytes, task, epoch, key_id="missing", command_id="foreign"), now_ms=NOW)

    assert result.reason == "UNKNOWN_OR_REVOKED_KEY"
    assert store.events() == ()


def test_revoked_key_is_rejected(tmp_path):
    pipeline, _, task, private_bytes, epoch, _, store, gateway = build(tmp_path)
    trusted = gateway.key_registry.resolve("key-v1", "operator-1")
    gateway.key_registry = type(gateway.key_registry)(
        [type(trusted)(trusted.key_id, trusted.source_id, trusted.public_key_bytes, revoked=True)]
    )
    result = pipeline.process(command_for(private_bytes, task, epoch), now_ms=NOW)

    assert result.reason == "UNKNOWN_OR_REVOKED_KEY"
    assert store.events() == ()


def test_adapter_failure_is_indeterminate_and_not_retried(tmp_path):
    pipeline, _, task, private_bytes, epoch, _, store, _ = build(tmp_path)

    def fail(**kwargs):
        raise RuntimeError("disk full")

    store.record = fail
    command = command_for(private_bytes, task, epoch)
    failed = pipeline.process(command, now_ms=NOW)
    store.record = DurableSimulationStore.record.__get__(store, DurableSimulationStore)
    retry = pipeline.process(command, now_ms=NOW)
    incomplete = store.reserved_without_event(pipeline.gateway.replay_store.database_path)

    assert failed.status == PipelineStatus.INDETERMINATE
    assert failed.reason == "ADAPTER_FAILURE"
    assert retry.reason == "DUPLICATE_COMMAND"
    assert incomplete == ("command-e2e",)
    assert store.events() == ()


def test_no_path_authorizes_physical_execution(tmp_path):
    pipeline, _, task, private_bytes, epoch, _, _, _ = build(tmp_path)
    accepted = pipeline.process(command_for(private_bytes, task, epoch), now_ms=NOW)
    tampered = pipeline.process(
        dataclasses.replace(command_for(private_bytes, task, epoch, command_id="tampered"), worker_id="robot-9"),
        now_ms=NOW,
    )

    assert accepted.physical_execution_authorized is False
    assert tampered.physical_execution_authorized is False
