from optimus_swarm.durable_simulator import DurableIdempotentSimulator
from optimus_swarm.simulation_execution import ExecutionStatus, InhibitSnapshot
from optimus_swarm.simulation_execution_controller import SimulationExecutionController
from optimus_swarm.simulation_journal import SimulationJournal
from optimus_swarm.startup_reconcile import reconcile_startup


class MutableInhibit:
    def __init__(self):
        self.latched = False
        self.revision = 1

    def snapshot(self):
        return InhibitSnapshot(latched=self.latched, revision=self.revision)


def test_durable_effect_survives_restart(tmp_path):
    path = str(tmp_path / "simulator.sqlite3")
    first = DurableIdempotentSimulator(path)
    applied = first.apply_once(command_id="cmd-1", event_digest="event-digest-1", now_ms=200)
    reopened = DurableIdempotentSimulator(path)
    again = reopened.apply_once(command_id="cmd-1", event_digest="event-digest-1", now_ms=300)

    assert applied.already_applied is False
    assert again.already_applied is True
    assert again.outcome_digest == applied.outcome_digest
    assert reopened.applied_ids() == ("cmd-1",)


def test_recorded_event_executes_once_across_restart(tmp_path):
    journal = SimulationJournal(str(tmp_path / "journal.db"))
    simulator_path = str(tmp_path / "simulator.sqlite3")
    journal.reserve("cmd-1", 100)
    journal.record_event("cmd-1", "event-digest-1", 101)
    controller = SimulationExecutionController(
        journal=journal,
        simulator=DurableIdempotentSimulator(simulator_path),
        inhibit=MutableInhibit(),
    )

    first = controller.execute_recorded(command_id="cmd-1", event_digest="event-digest-1", now_ms=200)
    restarted = SimulationExecutionController(
        journal=SimulationJournal(journal.database_path),
        simulator=DurableIdempotentSimulator(simulator_path),
        inhibit=MutableInhibit(),
    )
    second = restarted.execute_recorded(command_id="cmd-1", event_digest="event-digest-1", now_ms=201)

    assert first == ExecutionStatus.SIMULATION_EXECUTED
    assert second == ExecutionStatus.ALREADY_EXECUTED
    assert DurableIdempotentSimulator(simulator_path).applied_ids() == ("cmd-1",)


def test_crash_after_effect_is_not_resumed(tmp_path):
    journal = SimulationJournal(str(tmp_path / "journal.db"))
    simulator_path = str(tmp_path / "simulator.sqlite3")
    journal.reserve("cmd-1", 100)
    journal.record_event("cmd-1", "event-digest-1", 101)
    journal.claim_execution(
        command_id="cmd-1",
        expected_event_digest="event-digest-1",
        inhibit_revision=1,
        now_ms=200,
    )
    DurableIdempotentSimulator(simulator_path).apply_once(
        command_id="cmd-1",
        event_digest="event-digest-1",
        now_ms=200,
    )

    report = reconcile_startup(journal, simulator_path)
    controller = SimulationExecutionController(
        journal=journal,
        simulator=DurableIdempotentSimulator(simulator_path),
        inhibit=MutableInhibit(),
    )
    result = controller.execute_recorded(command_id="cmd-1", event_digest="event-digest-1", now_ms=300)

    assert report.status == "INDETERMINATE"
    assert report.auto_resumed is False
    assert report.physical_execution_authorized is False
    assert result == ExecutionStatus.INDETERMINATE
    assert journal.classify_execution("cmd-1") == "INDETERMINATE"
    assert DurableIdempotentSimulator(simulator_path).applied_ids() == ("cmd-1",)


def test_legacy_execution_is_not_promoted(tmp_path):
    journal = SimulationJournal(str(tmp_path / "journal.db"))
    journal.reserve("cmd-1", 100)
    journal.record_event("cmd-1", "event-digest-1", 101)
    with journal._connect() as db:
        db.execute(
            """
            INSERT INTO simulation_executions
            (command_id, execution_key, claimed_at_ms, outcome)
            VALUES ('cmd-1', 'exec:cmd-1', 150, 'SIMULATION_EXECUTED')
            """
        )

    report = reconcile_startup(journal, None)
    controller = SimulationExecutionController(
        journal=journal,
        simulator=DurableIdempotentSimulator(str(tmp_path / "simulator.sqlite3")),
        inhibit=MutableInhibit(),
    )
    result = controller.execute_recorded(command_id="cmd-1", event_digest="event-digest-1", now_ms=200)

    assert journal.unreconciled_legacy("cmd-1") is True
    assert report.items[0].classification == "INDETERMINATE"
    assert report.auto_resumed is False
    assert report.physical_execution_authorized is False
    assert result == ExecutionStatus.INDETERMINATE
    assert DurableIdempotentSimulator(str(tmp_path / "simulator.sqlite3")).applied_ids() == ()
