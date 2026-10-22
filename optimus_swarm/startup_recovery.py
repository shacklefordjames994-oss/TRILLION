import sqlite3
from contextlib import contextmanager

from optimus_swarm.epoch_models import EpochStatus, RecoveryItem, StartupRecoveryReport


class StartupRecovery:
    def __init__(self, database_path: str):
        self.database_path = database_path
        self._initialize()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database_path, timeout=10.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout = 10000")
            yield db
        finally:
            db.close()

    def _initialize(self):
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS recovery_journal (
                    journal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    coordinator_epoch INTEGER NOT NULL,
                    task_id TEXT NOT NULL,
                    old_generation INTEGER NOT NULL,
                    old_worker_id TEXT,
                    old_lease_id TEXT,
                    recovered_at_ms INTEGER NOT NULL,
                    reason TEXT NOT NULL
                )
                """
            )

    def recover(self, *, epoch: int, now_ms: int, startup_authority_verified: bool) -> StartupRecoveryReport:
        if epoch < 1 or now_ms < 0:
            return StartupRecoveryReport(status=EpochStatus.INDETERMINATE, epoch=max(epoch, 0), items=())

        # Placeholder Boolean only. Production must verify a signed,
        # authenticated startup authorization record.
        if not startup_authority_verified:
            return StartupRecoveryReport(status=EpochStatus.RECOVERY_REQUIRED, epoch=epoch, items=())

        recovered_items = []

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows = db.execute(
                    """
                    SELECT task_id, generation, worker_id, lease_id
                    FROM tasks
                    WHERE status = 'LEASED'
                    ORDER BY task_id
                    """
                ).fetchall()

                for row in rows:
                    db.execute(
                        """
                        INSERT INTO recovery_journal (
                            coordinator_epoch,
                            task_id,
                            old_generation,
                            old_worker_id,
                            old_lease_id,
                            recovered_at_ms,
                            reason
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            epoch,
                            row["task_id"],
                            row["generation"],
                            row["worker_id"],
                            row["lease_id"],
                            now_ms,
                            "COORDINATOR_RESTART",
                        ),
                    )
                    db.execute(
                        """
                        UPDATE tasks
                        SET status = 'PENDING',
                            generation = generation + 1,
                            worker_id = NULL,
                            lease_id = NULL,
                            lease_expires_at_ms = NULL
                        WHERE task_id = ?
                          AND status = 'LEASED'
                          AND generation = ?
                        """,
                        (row["task_id"], row["generation"]),
                    )
                    recovered_items.append(
                        RecoveryItem(
                            task_id=row["task_id"],
                            prior_generation=row["generation"],
                            prior_worker_id=row["worker_id"],
                            prior_lease_id=row["lease_id"],
                            reason="COORDINATOR_RESTART",
                        )
                    )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

        return StartupRecoveryReport(
            status=EpochStatus.RECOVERY_REQUIRED if recovered_items else EpochStatus.ACTIVE,
            epoch=epoch,
            items=tuple(recovered_items),
            physical_execution_authorized=False,
        )
