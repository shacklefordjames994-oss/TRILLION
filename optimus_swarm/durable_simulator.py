import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from optimus_swarm.simulation_execution import SimulatorResult


class DurableSimulatorError(RuntimeError):
    pass


class DurableIdempotentSimulator:
    """Simulation-only effect log. command_id is the durable idempotency key."""

    def __init__(self, database_path: str):
        self.database_path = str(Path(database_path))
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=5.0, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS simulator_effects (
                    command_id TEXT PRIMARY KEY,
                    event_digest TEXT NOT NULL,
                    outcome_digest TEXT NOT NULL,
                    applied_at_ms INTEGER NOT NULL
                )
                """
            )

    def apply_once(self, *, command_id: str, event_digest: str, now_ms: int = 0) -> SimulatorResult:
        if not command_id or not event_digest or now_ms < 0:
            return SimulatorResult(command_id=command_id or "", outcome_digest="", already_applied=False)

        outcome = hashlib.sha256(f"{command_id}:{event_digest}:SIMULATION".encode()).hexdigest()
        try:
            with self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT event_digest, outcome_digest FROM simulator_effects WHERE command_id = ?",
                    (command_id,),
                ).fetchone()
                if row is not None:
                    db.execute("ROLLBACK")
                    if row[0] != event_digest:
                        return SimulatorResult(command_id=command_id, outcome_digest="", already_applied=False)
                    return SimulatorResult(command_id=command_id, outcome_digest=row[1], already_applied=True)

                db.execute(
                    """
                    INSERT INTO simulator_effects
                    (command_id, event_digest, outcome_digest, applied_at_ms)
                    VALUES (?, ?, ?, ?)
                    """,
                    (command_id, event_digest, outcome, now_ms),
                )
                db.execute("COMMIT")
        except sqlite3.Error as exc:
            raise DurableSimulatorError("SIMULATOR_STORE_UNAVAILABLE") from exc

        return SimulatorResult(command_id=command_id, outcome_digest=outcome, already_applied=False)

    def applied_ids(self) -> tuple[str, ...]:
        with self._connect() as db:
            return tuple(row[0] for row in db.execute("SELECT command_id FROM simulator_effects ORDER BY command_id"))
