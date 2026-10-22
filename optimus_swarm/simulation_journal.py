import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class JournalError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionClaim:
    code: str
    physical_execution_authorized: bool = False


class SimulationJournal:
    def __init__(self, database_path: str):
        self.database_path = str(Path(database_path))
        self._initialize()
        self._ensure_execution_schema()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
            isolation_level=None,
        )
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS command_reservations (
                    command_id TEXT PRIMARY KEY,
                    reserved_at_ms INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS simulation_events (
                    command_id TEXT PRIMARY KEY,
                    event_digest TEXT NOT NULL,
                    recorded_at_ms INTEGER NOT NULL,
                    FOREIGN KEY(command_id)
                        REFERENCES command_reservations(command_id)
                );

                CREATE TABLE IF NOT EXISTS simulation_executions (
                    command_id TEXT PRIMARY KEY,
                    execution_key TEXT NOT NULL UNIQUE,
                    claimed_at_ms INTEGER NOT NULL,
                    outcome TEXT NOT NULL,
                    FOREIGN KEY(command_id)
                        REFERENCES simulation_events(command_id)
                );

                CREATE TABLE IF NOT EXISTS journal_incidents (
                    incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    detected_at_ms INTEGER NOT NULL
                );
                """
            )

    def reserve(self, command_id: str, now_ms: int) -> str:
        if not isinstance(command_id, str) or not command_id:
            raise ValueError("INVALID_RESERVATION")
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("INVALID_RESERVATION")

        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT 1 FROM command_reservations WHERE command_id = ?",
                    (command_id,),
                ).fetchone()

                if row:
                    db.execute("ROLLBACK")
                    return "ALREADY_RESERVED"

                db.execute(
                    """
                    INSERT INTO command_reservations
                    (command_id, reserved_at_ms) VALUES (?, ?)
                    """,
                    (command_id, now_ms),
                )
                db.execute("COMMIT")
                return "RESERVED"
        except sqlite3.Error as exc:
            raise JournalError("RESERVATION_FAILED") from exc

    def record_event(self, command_id: str, event_digest: str, now_ms: int) -> str:
        if not isinstance(command_id, str) or not command_id:
            raise ValueError("INVALID_EVENT")
        if not isinstance(event_digest, str) or not event_digest:
            raise ValueError("INVALID_EVENT")
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("INVALID_EVENT")

        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")

                reserved = db.execute(
                    "SELECT 1 FROM command_reservations WHERE command_id = ?",
                    (command_id,),
                ).fetchone()

                if not reserved:
                    db.execute("ROLLBACK")
                    return "NO_RESERVATION"

                existing = db.execute(
                    """
                    SELECT event_digest FROM simulation_events
                    WHERE command_id = ?
                    """,
                    (command_id,),
                ).fetchone()

                if existing:
                    db.execute("ROLLBACK")
                    if existing[0] == event_digest:
                        return "ALREADY_RECORDED"
                    return "EVENT_CONFLICT"

                db.execute(
                    """
                    INSERT INTO simulation_events
                    (command_id, event_digest, recorded_at_ms)
                    VALUES (?, ?, ?)
                    """,
                    (command_id, event_digest, now_ms),
                )
                db.execute("COMMIT")
                return "RECORDED"
        except sqlite3.Error as exc:
            raise JournalError("EVENT_RECORDING_FAILED") from exc

    def classify(self, command_id: str, now_ms: int) -> str:
        """Read-only recovery classification; never resumes work."""
        with self._connect() as db:
            reservation = db.execute(
                """
                SELECT 1 FROM command_reservations WHERE command_id = ?
                """,
                (command_id,),
            ).fetchone()
            event = db.execute(
                """
                SELECT 1 FROM simulation_events WHERE command_id = ?
                """,
                (command_id,),
            ).fetchone()
            execution = db.execute(
                """
                SELECT 1 FROM simulation_executions WHERE command_id = ?
                """,
                (command_id,),
            ).fetchone()

        if execution and not event:
            return "INDETERMINATE"
        if execution:
            return "ALREADY_EXECUTED"
        if event:
            return "RECORDED_NOT_EXECUTED"
        if reservation:
            return "RESERVED_WITHOUT_EVENT"
        return "NO_RECORDED_EVENT"

    def execute_recorded(
        self,
        command_id: str,
        event_digest: str,
        now_ms: int,
        *,
        inhibit_clear: Callable[[], bool],
        simulator,
        crash_at: str | None = None,
    ) -> ExecutionClaim:
        """
        Claim a recorded event once and hand it to an idempotent simulator.
        Recovery does not call this. A crash does not retry the effect.
        """
        if not isinstance(command_id, str) or not command_id or not isinstance(event_digest, str) or not event_digest:
            return ExecutionClaim("INVALID_EXECUTION")
        if type(now_ms) is not int or now_ms < 0:
            return ExecutionClaim("INVALID_EXECUTION")

        try:
            clear = inhibit_clear()
        except Exception:
            return ExecutionClaim("INHIBIT_UNAVAILABLE")
        if clear is not True:
            return ExecutionClaim("INHIBIT_LATCHED")

        if self._has_incident(command_id, "OUTCOME_UNKNOWN"):
            return ExecutionClaim("INDETERMINATE")

        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                event = db.execute(
                    "SELECT event_digest FROM simulation_events WHERE command_id = ?",
                    (command_id,),
                ).fetchone()
                if event is None:
                    db.execute("ROLLBACK")
                    return ExecutionClaim("NO_RECORDED_EVENT")
                if event[0] != event_digest:
                    db.execute("ROLLBACK")
                    return ExecutionClaim("DIGEST_MISMATCH")

                existing = db.execute(
                    "SELECT outcome FROM simulation_executions WHERE command_id = ?",
                    (command_id,),
                ).fetchone()
                if existing is not None:
                    db.execute("ROLLBACK")
                    if existing[0] == "SIMULATION_EXECUTED":
                        return ExecutionClaim("ALREADY_EXECUTED")
                    return ExecutionClaim("INDETERMINATE")

                try:
                    still_clear = inhibit_clear()
                except Exception:
                    db.execute("ROLLBACK")
                    return ExecutionClaim("INHIBIT_UNAVAILABLE")
                if still_clear is not True:
                    db.execute("ROLLBACK")
                    return ExecutionClaim("INHIBIT_LATCHED")

                if crash_at == "before_dispatch":
                    db.execute("ROLLBACK")
                    raise JournalError("CRASH_BEFORE_DISPATCH")

                try:
                    outcome = simulator.dispatch(command_id, event_digest, inhibit_clear=True)
                except Exception:
                    db.execute("ROLLBACK")
                    raise

                if crash_at in {"after_dispatch", "before_persist"}:
                    db.execute("ROLLBACK")
                    raise JournalError(
                        "CRASH_AFTER_DISPATCH" if crash_at == "after_dispatch" else "CRASH_BEFORE_PERSIST"
                    )

                if outcome != "SIMULATION_EXECUTED":
                    db.execute("ROLLBACK")
                    self._incident(command_id, "OUTCOME_UNKNOWN", now_ms)
                    return ExecutionClaim("INDETERMINATE")

                db.execute(
                    """
                    INSERT INTO simulation_executions
                    (command_id, execution_key, claimed_at_ms, outcome)
                    VALUES (?, ?, ?, 'SIMULATION_EXECUTED')
                    """,
                    (command_id, f"exec:{command_id}", now_ms),
                )
                db.execute("COMMIT")
                return ExecutionClaim("SIMULATION_EXECUTED")
        except JournalError:
            raise
        except sqlite3.IntegrityError:
            return ExecutionClaim("ALREADY_EXECUTED")
        except sqlite3.Error:
            return ExecutionClaim("INDETERMINATE")

    def _has_incident(self, command_id: str, code: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT 1 FROM journal_incidents
                WHERE command_id = ? AND code = ?
                """,
                (command_id, code),
            ).fetchone()
        return row is not None

    def _incident(self, command_id: str, code: str, now_ms: int) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO journal_incidents (command_id, code, detected_at_ms)
                VALUES (?, ?, ?)
                """,
                (command_id, code, now_ms),
            )

    def _ensure_execution_schema(self):
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS execution_claims (
                    command_id TEXT PRIMARY KEY,
                    event_digest TEXT NOT NULL,
                    inhibit_revision INTEGER NOT NULL,
                    claimed_at_ms INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('CLAIMED', 'INDETERMINATE', 'COMPLETED')
                    ),
                    FOREIGN KEY(command_id)
                        REFERENCES simulation_events(command_id)
                );

                CREATE TABLE IF NOT EXISTS execution_outcomes (
                    command_id TEXT PRIMARY KEY,
                    outcome_digest TEXT NOT NULL,
                    completed_at_ms INTEGER NOT NULL,
                    FOREIGN KEY(command_id)
                        REFERENCES execution_claims(command_id)
                );
                """
            )

    def claim_execution(
        self,
        *,
        command_id: str,
        expected_event_digest: str,
        inhibit_revision: int,
        now_ms: int,
    ) -> str:
        """Atomically claim a recorded event. Never retries an existing claim."""
        if not command_id or not expected_event_digest or inhibit_revision < 0 or now_ms < 0:
            raise ValueError("INVALID_EXECUTION_CLAIM")

        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                event = db.execute(
                    """
                    SELECT event_digest
                    FROM simulation_events
                    WHERE command_id = ?
                    """,
                    (command_id,),
                ).fetchone()

                if event is None:
                    db.execute("ROLLBACK")
                    return "NO_RECORDED_EVENT"

                if event[0] != expected_event_digest:
                    db.execute("ROLLBACK")
                    return "EVENT_DIGEST_MISMATCH"

                prior = db.execute(
                    """
                    SELECT state FROM execution_claims
                    WHERE command_id = ?
                    """,
                    (command_id,),
                ).fetchone()

                if prior:
                    db.execute("ROLLBACK")
                    return "ALREADY_EXECUTED" if prior[0] == "COMPLETED" else "EXECUTION_ALREADY_CLAIMED"

                db.execute(
                    """
                    INSERT INTO execution_claims (
                        command_id, event_digest, inhibit_revision,
                        claimed_at_ms, state
                    ) VALUES (?, ?, ?, ?, 'CLAIMED')
                    """,
                    (command_id, expected_event_digest, inhibit_revision, now_ms),
                )
                db.execute("COMMIT")
                return "CLAIMED"
        except sqlite3.Error as exc:
            raise JournalError("EXECUTION_CLAIM_FAILED") from exc

    def finalize_execution(self, *, command_id: str, outcome_digest: str, now_ms: int) -> str:
        """Commit a confirmed simulator outcome; never invent one."""
        if not command_id or not outcome_digest or now_ms < 0:
            raise ValueError("INVALID_EXECUTION_OUTCOME")

        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                claim = db.execute(
                    """
                    SELECT state FROM execution_claims
                    WHERE command_id = ?
                    """,
                    (command_id,),
                ).fetchone()

                if claim is None:
                    db.execute("ROLLBACK")
                    return "NO_EXECUTION_CLAIM"

                if claim[0] == "COMPLETED":
                    db.execute("ROLLBACK")
                    return "ALREADY_EXECUTED"

                if claim[0] != "CLAIMED":
                    db.execute("ROLLBACK")
                    return "INDETERMINATE"

                db.execute(
                    """
                    INSERT INTO execution_outcomes (
                        command_id, outcome_digest, completed_at_ms
                    ) VALUES (?, ?, ?)
                    """,
                    (command_id, outcome_digest, now_ms),
                )
                db.execute(
                    """
                    UPDATE execution_claims
                    SET state = 'COMPLETED'
                    WHERE command_id = ?
                    """,
                    (command_id,),
                )
                db.execute("COMMIT")
                return "SIMULATION_EXECUTED"
        except sqlite3.Error as exc:
            raise JournalError("EXECUTION_FINALIZATION_FAILED") from exc

    def mark_indeterminate(self, command_id: str) -> str:
        """Freeze an unresolved claim; never dispatch it again."""
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    """
                    SELECT state FROM execution_claims
                    WHERE command_id = ?
                    """,
                    (command_id,),
                ).fetchone()

                if row is None:
                    db.execute("ROLLBACK")
                    return "NO_EXECUTION_CLAIM"

                if row[0] == "COMPLETED":
                    db.execute("ROLLBACK")
                    return "ALREADY_EXECUTED"

                db.execute(
                    """
                    UPDATE execution_claims
                    SET state = 'INDETERMINATE'
                    WHERE command_id = ?
                    """,
                    (command_id,),
                )
                db.execute("COMMIT")
                return "INDETERMINATE"
        except sqlite3.Error as exc:
            raise JournalError("INDETERMINATE_UPDATE_FAILED") from exc

    def classify_execution(self, command_id: str) -> str:
        """Classify durable execution state without resuming work."""
        try:
            with self._connect() as db:
                event = db.execute(
                    """
                    SELECT event_digest
                    FROM simulation_events WHERE command_id = ?
                    """,
                    (command_id,),
                ).fetchone()
                claim = db.execute(
                    """
                    SELECT event_digest, state
                    FROM execution_claims WHERE command_id = ?
                    """,
                    (command_id,),
                ).fetchone()
                outcome = db.execute(
                    """
                    SELECT outcome_digest
                    FROM execution_outcomes WHERE command_id = ?
                    """,
                    (command_id,),
                ).fetchone()
                legacy_execution = db.execute(
                    """
                    SELECT 1 FROM simulation_executions
                    WHERE command_id = ?
                    """,
                    (command_id,),
                ).fetchone()
                reservation = db.execute(
                    """
                    SELECT 1 FROM command_reservations
                    WHERE command_id = ?
                    """,
                    (command_id,),
                ).fetchone()

            if (claim or outcome or legacy_execution) and not event:
                return "INDETERMINATE"
            if outcome and not claim:
                return "INDETERMINATE"
            if claim and event and claim[0] != event[0]:
                return "INDETERMINATE"
            if claim and claim[1] == "COMPLETED":
                if not outcome:
                    return "INDETERMINATE"
                return "ALREADY_EXECUTED"
            if outcome:
                return "INDETERMINATE"
            if claim:
                return "INDETERMINATE"
            if event:
                return "RECORDED_NOT_EXECUTED"
            if reservation:
                return "RESERVED_WITHOUT_EVENT"
            return "NO_RECORDED_EVENT"
        except sqlite3.Error as exc:
            raise JournalError("RECOVERY_CLASSIFICATION_FAILED") from exc

    def unreconciled_legacy(self, command_id: str) -> bool:
        """A Phase 18 execution row is not a Phase 19 completion."""
        with self._connect() as db:
            legacy = db.execute(
                "SELECT 1 FROM simulation_executions WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            if legacy is None:
                return False
            completed = db.execute(
                """
                SELECT 1
                FROM execution_claims AS claims
                JOIN execution_outcomes AS outcomes
                  ON outcomes.command_id = claims.command_id
                WHERE claims.command_id = ?
                  AND claims.state = 'COMPLETED'
                """,
                (command_id,),
            ).fetchone()
        return completed is None
