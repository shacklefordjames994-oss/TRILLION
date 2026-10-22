import sqlite3
from contextlib import contextmanager

from optimus_swarm.epoch_models import CoordinatorEpoch


class EpochStore:
    def __init__(self, database_path: str):
        self.database_path = database_path
        self._initialize()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database_path, timeout=10.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout = 10000")
            db.execute("PRAGMA foreign_keys = ON")
            yield db
        finally:
            db.close()

    def _initialize(self):
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS coordinator_epoch (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    coordinator_id TEXT NOT NULL,
                    epoch INTEGER NOT NULL CHECK (epoch >= 0),
                    started_at_ms INTEGER NOT NULL
                )
                """
            )

    def start_incarnation(self, coordinator_id: str, *, now_ms: int) -> CoordinatorEpoch:
        if not coordinator_id.strip() or now_ms < 0:
            raise ValueError("Invalid coordinator identity or timestamp")

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM coordinator_epoch WHERE singleton_id = 1").fetchone()
            next_epoch = 1 if row is None else row["epoch"] + 1
            db.execute(
                """
                INSERT INTO coordinator_epoch (
                    singleton_id, coordinator_id, epoch, started_at_ms
                )
                VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    coordinator_id = excluded.coordinator_id,
                    epoch = excluded.epoch,
                    started_at_ms = excluded.started_at_ms
                """,
                (coordinator_id, next_epoch, now_ms),
            )
            db.execute("COMMIT")

        return CoordinatorEpoch(coordinator_id=coordinator_id, epoch=next_epoch, started_at_ms=now_ms)

    def current(self) -> CoordinatorEpoch | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM coordinator_epoch WHERE singleton_id = 1").fetchone()

        if row is None:
            return None

        return CoordinatorEpoch(
            coordinator_id=row["coordinator_id"],
            epoch=row["epoch"],
            started_at_ms=row["started_at_ms"],
        )
