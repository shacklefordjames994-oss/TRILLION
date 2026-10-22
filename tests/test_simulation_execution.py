import pytest

from optimus_swarm.simulation_execution import ExecutionStatus, InhibitSnapshot
from optimus_swarm.simulation_execution_controller import SimulationExecutionController
from optimus_swarm.simulation_journal import SimulationJournal
from optimus_swarm.test_simulator import TestSimulator


class MutableInhibit:
    def __init__(self, latched=False, revision=1):
        self.latched = latched
        self.revision = revision

    def snapshot(self):
        return InhibitSnapshot(latched=self.latched, revision=self.revision)


@pytest.fixture
def setup(tmp_path):
    journal = SimulationJournal(str(tmp_path / "journal.db"))
    journal._ensure_execution_schema()
    simulator = TestSimulator()
    inhibit = MutableInhibit()
    controller = SimulationExecutionController(journal=journal, simulator=simulator, inhibit=inhibit)
    journal.reserve("cmd-1", 100)
    journal.record_event("cmd-1", "event-digest-1", 101)
    return journal, simulator, inhibit, controller


def test_recorded_event_executes_once(setup):
    journal, simulator, _, controller = setup
    first = controller.execute_recorded(command_id="cmd-1", event_digest="event-digest-1", now_ms=200)
    second = controller.execute_recorded(command_id="cmd-1", event_digest="event-digest-1", now_ms=201)

    assert first == ExecutionStatus.SIMULATION_EXECUTED
    assert second == ExecutionStatus.ALREADY_EXECUTED
    assert simulator.dispatch_count["cmd-1"] == 1
    assert journal.classify_execution("cmd-1") == "ALREADY_EXECUTED"


def test_latched_inhibit_does_not_execute(setup):
    journal, simulator, inhibit, controller = setup
    inhibit.latched = True
    inhibit.revision += 1

    result = controller.execute_recorded(command_id="cmd-1", event_digest="event-digest-1", now_ms=200)

    assert result == ExecutionStatus.REJECTED
    assert simulator.dispatch_count == {}
    assert journal.classify_execution("cmd-1") == "RECORDED_NOT_EXECUTED"


def test_unrecorded_command_is_rejected(setup):
    journal, simulator, _, controller = setup
    result = controller.execute_recorded(command_id="missing", event_digest="missing-digest", now_ms=200)

    assert result == ExecutionStatus.REJECTED
    assert simulator.dispatch_count == {}
    assert journal.classify_execution("missing") == "NO_RECORDED_EVENT"


def test_reserved_without_event_is_not_executed(setup):
    journal, simulator, _, controller = setup
    journal.reserve("cmd-2", 110)

    assert journal.classify_execution("cmd-2") == "RESERVED_WITHOUT_EVENT"
    result = controller.execute_recorded(command_id="cmd-2", event_digest="event-digest-2", now_ms=200)

    assert result == ExecutionStatus.REJECTED
    assert simulator.dispatch_count == {}


def test_recorded_but_not_executed_stays_pending(setup):
    journal, _, _, _ = setup
    assert journal.classify_execution("cmd-1") == "RECORDED_NOT_EXECUTED"


def test_claimed_command_is_not_resumed(setup):
    journal, simulator, _, _ = setup
    result = journal.claim_execution(
        command_id="cmd-1",
        expected_event_digest="event-digest-1",
        inhibit_revision=1,
        now_ms=200,
    )

    assert result == "CLAIMED"
    assert journal.classify_execution("cmd-1") == "INDETERMINATE"
    assert simulator.dispatch_count == {}


def test_execution_without_event_is_indeterminate(setup):
    journal, _, _, _ = setup
    with journal._connect() as db:
        db.execute("PRAGMA foreign_keys = OFF")
        db.execute(
            """
            INSERT INTO simulation_executions
            (command_id, execution_key, claimed_at_ms, outcome)
            VALUES ('orphan', 'exec:orphan', 200, 'SIMULATION_EXECUTED')
            """
        )

    assert journal.classify_execution("orphan") == "INDETERMINATE"


def test_simulator_crash_is_not_retried(setup):
    journal, _, _, controller = setup

    class CrashingSimulator:
        def __init__(self):
            self.calls = 0

        def apply_once(self, *, command_id, event_digest):
            self.calls += 1
            raise RuntimeError("crash after receive")

    crashing = CrashingSimulator()
    controller.simulator = crashing
    first = controller.execute_recorded(command_id="cmd-1", event_digest="event-digest-1", now_ms=200)
    second = controller.execute_recorded(command_id="cmd-1", event_digest="event-digest-1", now_ms=201)

    assert first == ExecutionStatus.INDETERMINATE
    assert second == ExecutionStatus.INDETERMINATE
    assert crashing.calls == 1
    assert journal.classify_execution("cmd-1") == "INDETERMINATE"
