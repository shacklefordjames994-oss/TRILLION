import sqlite3
from dataclasses import dataclass

from optimus_swarm.simulation_journal import JournalError, SimulationJournal


@dataclass(frozen=True)
class ReconciliationItem:
    command_id: str
    classification: str


@dataclass(frozen=True)
class StartupReconciliation:
    status: str
    items: tuple[ReconciliationItem, ...]
    auto_resumed: bool = False
    physical_execution_authorized: bool = False


def reconcile_startup(journal: SimulationJournal, simulator_database_path: str | None = None) -> StartupReconciliation:
    """Classify journal and simulator state. Does not execute, finalize, or resume."""
    try:
        command_ids = set(_journal_ids(journal))
        effects = _effect_ids(simulator_database_path) if simulator_database_path else set()
        command_ids.update(effects)
    except (sqlite3.Error, OSError, JournalError):
        return StartupReconciliation("INDETERMINATE", (ReconciliationItem("*", "RECOVERY_UNAVAILABLE"),))

    items: list[ReconciliationItem] = []
    for command_id in sorted(command_ids):
        classification = journal.classify_execution(command_id)
        if journal.unreconciled_legacy(command_id):
            classification = "INDETERMINATE"
        elif command_id in effects and classification != "ALREADY_EXECUTED":
            classification = "INDETERMINATE"
        items.append(ReconciliationItem(command_id, classification))

    if any(item.classification == "INDETERMINATE" for item in items):
        status = "INDETERMINATE"
    elif any(item.classification != "ALREADY_EXECUTED" for item in items):
        status = "HELD"
    else:
        status = "READY"
    return StartupReconciliation(status, tuple(items))


def _journal_ids(journal: SimulationJournal) -> set[str]:
    with journal._connect() as db:
        rows = []
        for table in (
            "command_reservations",
            "simulation_events",
            "simulation_executions",
            "execution_claims",
            "execution_outcomes",
        ):
            rows.extend(db.execute(f"SELECT command_id FROM {table}").fetchall())
    return {row[0] for row in rows}


def _effect_ids(database_path: str) -> set[str]:
    connection = sqlite3.connect(database_path, timeout=5.0)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "simulator_effects" not in tables:
            return set()
        return {row[0] for row in connection.execute("SELECT command_id FROM simulator_effects")}
    finally:
        connection.close()
