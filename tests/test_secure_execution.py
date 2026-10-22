from optimus_swarm.command_crypto import generate_keypair, sign_command
from optimus_swarm.durable_replay_store import DurableReplayStore
from optimus_swarm.durable_simulation_store import DurableSimulationStore
from optimus_swarm.execution_models import ExecutionStatus
from optimus_swarm.inhibit_state import InhibitState
from optimus_swarm.integration_models import PipelineStatus
from optimus_swarm.secure_command_models import CommandDecision, DecisionStatus
from optimus_swarm.simulation_executor import SimulationExecutor, recover_after_crash
from tests.test_end_to_end_pipeline import build, command_for

NOW = 100_000


def test_recorded_event_executes_once_in_simulation(tmp_path):
    pipeline, _, task, private_bytes, epoch, inhibit, store, _ = build(tmp_path)
    command = command_for(private_bytes, task, epoch)
    recorded = pipeline.process(command, now_ms=NOW)
    executor = SimulationExecutor(store, inhibit_snapshot=lambda: (inhibit.snapshot().latched, inhibit.snapshot().revision))
    first = executor.execute(command.command_id, now_ms=NOW + 1)
    second = executor.execute(command.command_id, now_ms=NOW + 2)
    reopened = SimulationExecutor(
        DurableSimulationStore(store.database_path),
        inhibit_snapshot=lambda: (False, 1),
    )
    after_restart = reopened.execute(command.command_id, now_ms=NOW + 3)

    assert recorded.status == PipelineStatus.ACCEPTED
    assert first.status == ExecutionStatus.EXECUTED
    assert first.reason == "SIMULATION_EXECUTED"
    assert first.physical_execution_authorized is False
    assert second.status == ExecutionStatus.ALREADY_EXECUTED
    assert after_restart.status == ExecutionStatus.ALREADY_EXECUTED


def test_inhibit_blocks_execution_of_recorded_event(tmp_path):
    pipeline, _, task, private_bytes, epoch, inhibit, store, _ = build(tmp_path)
    command = command_for(private_bytes, task, epoch)
    pipeline.process(command, now_ms=NOW)
    inhibit.engage(reason="stop before execution", now_ms=NOW + 1)
    receipt = SimulationExecutor(
        store,
        inhibit_snapshot=lambda: (inhibit.snapshot().latched, inhibit.snapshot().revision),
    ).execute(command.command_id, now_ms=NOW + 2)

    assert receipt.status == ExecutionStatus.REJECTED
    assert receipt.reason == "INHIBIT_LATCHED"
    assert store.get_execution(command.command_id) is None


def test_missing_event_is_not_executed(tmp_path):
    store = DurableSimulationStore(str(tmp_path / "events.sqlite3"))
    receipt = SimulationExecutor(store, inhibit_snapshot=lambda: (False, 1)).execute("missing", now_ms=NOW)

    assert receipt.reason == "EVENT_NOT_RECORDED"
    assert receipt.physical_execution_authorized is False


def test_crash_does_not_resume_or_duplicate(tmp_path):
    pipeline, _, task, private_bytes, epoch, _, store, gateway = build(tmp_path)
    reserved = command_for(private_bytes, task, epoch, command_id="reserved-only")
    gateway.authorize_simulation(reserved, now_ms=NOW)
    recorded = command_for(private_bytes, task, epoch, command_id="recorded-only")
    pipeline.process(recorded, now_ms=NOW)

    report = recover_after_crash(store, gateway.replay_store.database_path)
    classifications = {item.command_id: item.classification for item in report.items}

    assert report.auto_resumed is False
    assert report.physical_execution_authorized is False
    assert report.status == "HELD"
    assert classifications["reserved-only"] == "RESERVED_WITHOUT_EVENT"
    assert classifications["recorded-only"] == "RECORDED_NOT_EXECUTED"
    assert store.execution_ids() == ()


def test_execution_without_event_is_indeterminate(tmp_path):
    store = DurableSimulationStore(str(tmp_path / "events.sqlite3"))
    replay = DurableReplayStore(str(tmp_path / "replay.sqlite3"))
    store.record_execution(command_id="orphan", operation="simulate_navigation", now_ms=NOW)
    report = recover_after_crash(store, replay.database_path)

    assert report.status == "INDETERMINATE"
    assert report.items[0].classification == "INCONSISTENT_EXECUTION"
    assert report.auto_resumed is False
