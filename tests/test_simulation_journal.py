import sqlite3

import pytest

from optimus_swarm.simulation_journal import JournalError, SimulationJournal
from optimus_swarm.simulator_contract import IdempotentSimulator

NOW = 100_000
DIGEST = "a" * 64


def journal(tmp_path) -> SimulationJournal:
    return SimulationJournal(str(tmp_path / "journal.sqlite3"))


def recorded(tmp_path) -> tuple[SimulationJournal, IdempotentSimulator]:
    book = journal(tmp_path)
    assert book.reserve("cmd-1", NOW) == "RESERVED"
    assert book.record_event("cmd-1", DIGEST, NOW) == "RECORDED"
    return book, IdempotentSimulator()


def test_clear_inhibit_executes_once(tmp_path):
    book, simulator = recorded(tmp_path)
    first = book.execute_recorded("cmd-1", DIGEST, NOW, inhibit_clear=lambda: True, simulator=simulator)
    second = book.execute_recorded("cmd-1", DIGEST, NOW + 1, inhibit_clear=lambda: True, simulator=simulator)

    assert first.code == "SIMULATION_EXECUTED"
    assert first.physical_execution_authorized is False
    assert second.code == "ALREADY_EXECUTED"
    assert second.physical_execution_authorized is False
    assert simulator.effect_count == 1
    assert book.classify("cmd-1", NOW) == "ALREADY_EXECUTED"


def test_latched_inhibit_does_not_claim_execution(tmp_path):
    book, simulator = recorded(tmp_path)
    claim = book.execute_recorded("cmd-1", DIGEST, NOW, inhibit_clear=lambda: False, simulator=simulator)

    assert claim.code == "INHIBIT_LATCHED"
    assert claim.physical_execution_authorized is False
    assert simulator.effect_count == 0
    assert book.classify("cmd-1", NOW) == "RECORDED_NOT_EXECUTED"


def test_missing_event_is_rejected(tmp_path):
    book = journal(tmp_path)
    book.reserve("cmd-1", NOW)
    claim = book.execute_recorded("cmd-1", DIGEST, NOW, inhibit_clear=lambda: True, simulator=IdempotentSimulator())

    assert claim.code == "NO_RECORDED_EVENT"
    assert book.classify("cmd-1", NOW) == "RESERVED_WITHOUT_EVENT"


def test_classify_does_not_execute(tmp_path):
    book, simulator = recorded(tmp_path)
    assert book.classify("cmd-1", NOW) == "RECORDED_NOT_EXECUTED"
    assert simulator.effect_count == 0
    assert book.classify("missing", NOW) == "NO_RECORDED_EVENT"


def test_execution_without_event_is_indeterminate(tmp_path):
    book = journal(tmp_path)
    connection = sqlite3.connect(book.database_path)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(
        """
        INSERT INTO simulation_executions
        (command_id, execution_key, claimed_at_ms, outcome)
        VALUES ('orphan', 'exec:orphan', ?, 'SIMULATION_EXECUTED')
        """,
        (NOW,),
    )
    connection.commit()
    connection.close()

    assert book.classify("orphan", NOW) == "INDETERMINATE"


def test_duplicate_reservation_and_conflicting_event(tmp_path):
    book = journal(tmp_path)
    assert book.reserve("cmd-1", NOW) == "RESERVED"
    assert book.reserve("cmd-1", NOW) == "ALREADY_RESERVED"
    assert book.record_event("cmd-1", DIGEST, NOW) == "RECORDED"
    assert book.record_event("cmd-1", DIGEST, NOW) == "ALREADY_RECORDED"
    assert book.record_event("cmd-1", "b" * 64, NOW) == "EVENT_CONFLICT"


def test_crash_before_dispatch_leaves_event_unexecuted(tmp_path):
    book, simulator = recorded(tmp_path)
    with pytest.raises(JournalError, match="CRASH_BEFORE_DISPATCH"):
        book.execute_recorded(
            "cmd-1",
            DIGEST,
            NOW,
            inhibit_clear=lambda: True,
            simulator=simulator,
            crash_at="before_dispatch",
        )

    assert simulator.effect_count == 0
    assert book.classify("cmd-1", NOW) == "RECORDED_NOT_EXECUTED"
    claim = book.execute_recorded("cmd-1", DIGEST, NOW, inhibit_clear=lambda: True, simulator=simulator)
    assert claim.code == "SIMULATION_EXECUTED"
    assert simulator.effect_count == 1


@pytest.mark.parametrize("crash_at", ["after_dispatch", "before_persist"])
def test_crash_after_simulator_does_not_apply_twice(tmp_path, crash_at):
    book, simulator = recorded(tmp_path)
    with pytest.raises(JournalError):
        book.execute_recorded(
            "cmd-1",
            DIGEST,
            NOW,
            inhibit_clear=lambda: True,
            simulator=simulator,
            crash_at=crash_at,
        )

    assert simulator.effect_count == 1
    assert book.classify("cmd-1", NOW) == "RECORDED_NOT_EXECUTED"

    claim = book.execute_recorded("cmd-1", DIGEST, NOW + 1, inhibit_clear=lambda: True, simulator=simulator)
    assert claim.code == "SIMULATION_EXECUTED"
    assert claim.physical_execution_authorized is False
    assert simulator.effect_count == 1


def test_unknown_simulator_outcome_is_not_retried(tmp_path):
    book, _ = recorded(tmp_path)

    class UnknownSimulator:
        def __init__(self):
            self.calls = 0

        def dispatch(self, command_id, event_digest, *, inhibit_clear):
            self.calls += 1
            return "INDETERMINATE"

    simulator = UnknownSimulator()
    first = book.execute_recorded("cmd-1", DIGEST, NOW, inhibit_clear=lambda: True, simulator=simulator)
    second = book.execute_recorded("cmd-1", DIGEST, NOW + 1, inhibit_clear=lambda: True, simulator=simulator)

    assert first.code == "INDETERMINATE"
    assert second.code == "INDETERMINATE"
    assert simulator.calls == 1
    assert book.classify("cmd-1", NOW) == "RECORDED_NOT_EXECUTED"
