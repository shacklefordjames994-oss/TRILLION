import sqlite3
from contextlib import contextmanager
from pathlib import Path

from optimus_swarm.integration_adapter import SimulationEvent
from optimus_swarm.secure_command_models import CommandDecision, DecisionStatus


class DurableSimulationStore:
    """Durable simulation-event log. A restart must not create a second event."""

    def __init__(self, database_path: str):
        self.database_path = str(Path(database_path))
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS simulation_events (
                    command_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    operation TEXT NOT NULL,
                    payload_digest TEXT NOT NULL,
                    recorded_at_ms INTEGER NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'SIMULATION_ONLY'
                        CHECK (mode = 'SIMULATION_ONLY')
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS simulation_executions (
                    command_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    executed_at_ms INTEGER NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'SIMULATION_ONLY'
                        CHECK (mode = 'SIMULATION_ONLY'),
                    physical_execution_authorized INTEGER NOT NULL DEFAULT 0
                        CHECK (physical_execution_authorized = 0)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS command_journal (
                    command_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_digest TEXT,
                    decision_code TEXT,
                    coordinator_epoch INTEGER,
                    recorded_at_ms INTEGER NOT NULL,
                    physical_execution_authorized INTEGER NOT NULL DEFAULT 0
                        CHECK (physical_execution_authorized = 0)
                )
                """
            )

    def record(
        self,
        *,
        decision: CommandDecision,
        operation: str,
        payload_digest: str,
        now_ms: int,
    ) -> SimulationEvent:
        if decision.status != DecisionStatus.ACCEPTED:
            raise PermissionError("COMMAND_NOT_ACCEPTED")
        if not decision.simulation_permitted:
            raise PermissionError("SIMULATION_NOT_PERMITTED")
        if decision.physical_execution_authorized:
            raise PermissionError("PHYSICAL_EXECUTION_MUST_REMAIN_DISABLED")
        if not operation or not payload_digest or now_ms < 0:
            raise ValueError("INVALID_SIMULATION_EVENT")

        event = SimulationEvent(
            event_id=f"sim:{decision.command_id}",
            command_id=decision.command_id,
            operation=operation,
            payload_digest=payload_digest,
            recorded_at_ms=now_ms,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO simulation_events (
                        command_id, event_id, operation, payload_digest, recorded_at_ms, mode
                    ) VALUES (?, ?, ?, ?, ?, 'SIMULATION_ONLY')
                    """,
                    (event.command_id, event.event_id, event.operation, event.payload_digest, event.recorded_at_ms),
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError:
                connection.execute("ROLLBACK")
                raise ValueError("DUPLICATE_SIMULATION_EVENT") from None
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return event

    def get_event(self, command_id: str) -> SimulationEvent | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM simulation_events WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        if row is None:
            return None
        return SimulationEvent(
            event_id=row["event_id"],
            command_id=row["command_id"],
            operation=row["operation"],
            payload_digest=row["payload_digest"],
            recorded_at_ms=row["recorded_at_ms"],
            mode=row["mode"],
        )

    def record_execution(self, *, command_id: str, operation: str, now_ms: int) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO simulation_executions (
                        command_id, operation, executed_at_ms, mode, physical_execution_authorized
                    ) VALUES (?, ?, ?, 'SIMULATION_ONLY', 0)
                    """,
                    (command_id, operation, now_ms),
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError:
                connection.execute("ROLLBACK")
                raise ValueError("DUPLICATE_EXECUTION") from None
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def get_execution(self, command_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT operation FROM simulation_executions WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        return None if row is None else row["operation"]

    def execution_ids(self) -> tuple[str, ...]:
        with self._connect() as connection:
            return tuple(row[0] for row in connection.execute("SELECT command_id FROM simulation_executions").fetchall())

    def events(self) -> tuple[SimulationEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM simulation_events ORDER BY command_id"
            ).fetchall()
        return tuple(
            SimulationEvent(
                event_id=row["event_id"],
                command_id=row["command_id"],
                operation=row["operation"],
                payload_digest=row["payload_digest"],
                recorded_at_ms=row["recorded_at_ms"],
                mode=row["mode"],
            )
            for row in rows
        )

    def journal(
        self,
        *,
        command_id: str,
        status: str,
        stage: str,
        reason: str,
        now_ms: int,
        payload_digest: str = "",
        decision_code: str = "",
        coordinator_epoch: int | None = None,
    ) -> None:
        if not command_id:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO command_journal (
                    command_id, status, stage, reason, payload_digest,
                    decision_code, coordinator_epoch, recorded_at_ms,
                    physical_execution_authorized
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                ON CONFLICT(command_id) DO UPDATE SET
                    status = excluded.status,
                    stage = excluded.stage,
                    reason = excluded.reason,
                    payload_digest = excluded.payload_digest,
                    decision_code = excluded.decision_code,
                    coordinator_epoch = excluded.coordinator_epoch,
                    recorded_at_ms = excluded.recorded_at_ms
                """,
                (
                    command_id,
                    status,
                    stage,
                    reason,
                    payload_digest,
                    decision_code,
                    coordinator_epoch,
                    now_ms,
                ),
            )

    def reserved_without_event(self, replay_database_path: str) -> tuple[str, ...]:
        """Commands reserved for replay that have no simulation event. Does not create events."""
        with self._connect() as events:
            recorded = {
                row[0]
                for row in events.execute("SELECT command_id FROM simulation_events").fetchall()
            }
        connection = sqlite3.connect(replay_database_path, timeout=5.0)
        try:
            reserved = [row[0] for row in connection.execute("SELECT command_id FROM accepted_commands").fetchall()]
        finally:
            connection.close()
        return tuple(sorted(command_id for command_id in reserved if command_id not in recorded))
