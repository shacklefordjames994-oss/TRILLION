import sqlite3
import uuid

from optimus_swarm.durable_models import DurableDecision, DurableTask, DurableTaskStatus
from optimus_swarm.epoch_guard import CoordinatorMessage, validate_coordinator_message


class DurableCoordinator:
    """
    Single-database task coordinator.

    Guarantees are limited to transactions in this SQLite database.
    All returned decisions deny physical execution.
    """

    def __init__(self, database_path: str):
        self.database_path = database_path
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS workers (
                    worker_id TEXT PRIMARY KEY,
                    healthy INTEGER NOT NULL
                        CHECK (healthy IN (0, 1))
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    payload_digest TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    generation INTEGER NOT NULL DEFAULT 0,
                    worker_id TEXT,
                    lease_id TEXT,
                    lease_expires_at_ms INTEGER,
                    CHECK (generation >= 0),
                    CHECK (
                        (status = 'LEASED'
                         AND worker_id IS NOT NULL
                         AND lease_id IS NOT NULL
                         AND lease_expires_at_ms IS NOT NULL)
                        OR
                        (status != 'LEASED'
                         AND worker_id IS NULL
                         AND lease_id IS NULL
                         AND lease_expires_at_ms IS NULL)
                    )
                )
                """
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS completions (
                    task_id TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    completion_key TEXT NOT NULL,
                    result_digest TEXT NOT NULL,
                    completed_at_ms INTEGER NOT NULL,
                    PRIMARY KEY (task_id, generation),
                    UNIQUE (completion_key),
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                )
                """
            )

    @staticmethod
    def _valid_text(value):
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _valid_digest(value):
        if not isinstance(value, str) or len(value) != 64:
            return False
        try:
            int(value, 16)
            return True
        except ValueError:
            return False

    @staticmethod
    def _row_to_task(row):
        if row is None:
            return None
        return DurableTask(
            task_id=row["task_id"],
            payload_digest=row["payload_digest"],
            priority=row["priority"],
            status=DurableTaskStatus(row["status"]),
            generation=row["generation"],
            worker_id=row["worker_id"],
            lease_id=row["lease_id"],
            lease_expires_at_ms=row["lease_expires_at_ms"],
        )

    def _epoch_rejection(self, db, *, task_id: str, claimed_coordinator_id, claimed_epoch, message_id: str, generation: int):
        try:
            row = db.execute(
                "SELECT coordinator_id, epoch FROM coordinator_epoch WHERE singleton_id = 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None
        if not claimed_coordinator_id or claimed_epoch is None:
            return "EPOCH_REQUIRED"
        decision = validate_coordinator_message(
            CoordinatorMessage(
                coordinator_id=claimed_coordinator_id,
                epoch=claimed_epoch,
                message_id=message_id,
                task_id=task_id,
                generation=generation if generation >= 1 else 1,
            ),
            active_coordinator_id=row["coordinator_id"],
            active_epoch=row["epoch"],
        )
        return None if decision.accepted else decision.code

    def register_worker(self, worker_id: str) -> DurableDecision:
        if not self._valid_text(worker_id):
            return DurableDecision(False, "INVALID_WORKER_ID")

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT INTO workers(worker_id, healthy)
                VALUES (?, 1)
                ON CONFLICT(worker_id)
                DO UPDATE SET healthy = 1
                """,
                (worker_id,),
            )
            db.execute("COMMIT")

        return DurableDecision(True, "WORKER_REGISTERED")

    def set_worker_health(self, worker_id: str, *, healthy: bool) -> DurableDecision:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "UPDATE workers SET healthy = ? WHERE worker_id = ?",
                (int(healthy), worker_id),
            )
            if cursor.rowcount != 1:
                db.execute("ROLLBACK")
                return DurableDecision(False, "UNKNOWN_WORKER")

            db.execute("COMMIT")

        return DurableDecision(True, "WORKER_HEALTH_UPDATED")

    def submit(self, task_id: str, payload_digest: str, *, priority: int = 0) -> DurableDecision:
        if not self._valid_text(task_id):
            return DurableDecision(False, "INVALID_TASK_ID")

        if not self._valid_digest(payload_digest):
            return DurableDecision(False, "INVALID_PAYLOAD_DIGEST")

        if not isinstance(priority, int) or isinstance(priority, bool):
            return DurableDecision(False, "INVALID_PRIORITY")

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    """
                    INSERT INTO tasks (
                        task_id, payload_digest, priority, status
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (task_id, payload_digest.lower(), priority, DurableTaskStatus.PENDING.value),
                )
                row = db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
                db.execute("COMMIT")
                return DurableDecision(True, "TASK_SUBMITTED", self._row_to_task(row))
            except sqlite3.IntegrityError:
                db.execute("ROLLBACK")
                return DurableDecision(False, "DUPLICATE_TASK_ID")

    def get_task(self, task_id: str) -> DurableTask | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            return self._row_to_task(row)

    def assign(
        self,
        task_id: str,
        worker_id: str,
        *,
        now_ms: int,
        lease_duration_ms: int,
        claimed_coordinator_id: str | None = None,
        claimed_epoch: int | None = None,
        message_id: str = "assign",
    ) -> DurableDecision:
        if now_ms < 0 or lease_duration_ms <= 0:
            return DurableDecision(False, "INVALID_TIME")

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            epoch_code = self._epoch_rejection(
                db,
                task_id=task_id,
                claimed_coordinator_id=claimed_coordinator_id,
                claimed_epoch=claimed_epoch,
                message_id=message_id,
                generation=1,
            )
            if epoch_code:
                db.execute("ROLLBACK")
                return DurableDecision(False, epoch_code)

            worker = db.execute("SELECT healthy FROM workers WHERE worker_id = ?", (worker_id,)).fetchone()
            if worker is None:
                db.execute("ROLLBACK")
                return DurableDecision(False, "UNKNOWN_WORKER")

            if worker["healthy"] != 1:
                db.execute("ROLLBACK")
                return DurableDecision(False, "WORKER_UNHEALTHY")

            row = db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                return DurableDecision(False, "UNKNOWN_TASK")

            if row["status"] in (DurableTaskStatus.COMPLETED.value, DurableTaskStatus.CANCELLED.value):
                db.execute("ROLLBACK")
                return DurableDecision(False, "TASK_TERMINAL")

            if row["status"] == DurableTaskStatus.LEASED.value and row["lease_expires_at_ms"] > now_ms:
                db.execute("ROLLBACK")
                return DurableDecision(False, "TASK_ALREADY_LEASED")

            active = db.execute(
                """
                SELECT task_id FROM tasks
                WHERE status = ?
                  AND worker_id = ?
                  AND lease_expires_at_ms > ?
                LIMIT 1
                """,
                (DurableTaskStatus.LEASED.value, worker_id, now_ms),
            ).fetchone()

            if active is not None and active["task_id"] != task_id:
                db.execute("ROLLBACK")
                return DurableDecision(False, "WORKER_ALREADY_LEASED")

            generation = row["generation"] + 1
            lease_id = str(uuid.uuid4())
            expires_at_ms = now_ms + lease_duration_ms
            db.execute(
                """
                UPDATE tasks
                SET status = ?,
                    generation = ?,
                    worker_id = ?,
                    lease_id = ?,
                    lease_expires_at_ms = ?
                WHERE task_id = ?
                """,
                (DurableTaskStatus.LEASED.value, generation, worker_id, lease_id, expires_at_ms, task_id),
            )
            updated = db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            db.execute("COMMIT")
            return DurableDecision(True, "LEASE_GRANTED", self._row_to_task(updated))

    def complete(
        self,
        task_id: str,
        worker_id: str,
        *,
        generation: int,
        lease_id: str,
        completion_key: str,
        result_digest: str,
        now_ms: int,
        claimed_coordinator_id: str | None = None,
        claimed_epoch: int | None = None,
        message_id: str = "complete",
    ) -> DurableDecision:
        if now_ms < 0 or generation < 1:
            return DurableDecision(False, "INVALID_COMPLETION_TIME_OR_GENERATION")

        if not all(self._valid_text(value) for value in (task_id, worker_id, lease_id, completion_key)):
            return DurableDecision(False, "INVALID_COMPLETION_IDENTITY")

        if not self._valid_digest(result_digest):
            return DurableDecision(False, "INVALID_RESULT_DIGEST")

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            epoch_code = self._epoch_rejection(
                db,
                task_id=task_id,
                claimed_coordinator_id=claimed_coordinator_id,
                claimed_epoch=claimed_epoch,
                message_id=message_id,
                generation=generation,
            )
            if epoch_code:
                db.execute("ROLLBACK")
                return DurableDecision(False, epoch_code)

            row = db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                return DurableDecision(False, "UNKNOWN_TASK")

            prior = db.execute(
                """
                SELECT completion_key, result_digest
                FROM completions
                WHERE task_id = ? AND generation = ?
                """,
                (task_id, generation),
            ).fetchone()

            if prior is not None:
                same_request = (
                    prior["completion_key"] == completion_key
                    and prior["result_digest"] == result_digest.lower()
                    and row["status"] == DurableTaskStatus.COMPLETED.value
                    and row["generation"] == generation
                )
                db.execute("COMMIT")
                return DurableDecision(
                    same_request,
                    "IDEMPOTENT_REPLAY" if same_request else "CONFLICTING_COMPLETION",
                    self._row_to_task(row),
                )

            if row["status"] != DurableTaskStatus.LEASED.value:
                db.execute("ROLLBACK")
                return DurableDecision(False, "TASK_NOT_LEASED")

            if row["generation"] != generation:
                db.execute("ROLLBACK")
                return DurableDecision(False, "STALE_FENCING_TOKEN")

            if row["worker_id"] != worker_id or row["lease_id"] != lease_id:
                db.execute("ROLLBACK")
                return DurableDecision(False, "LEASE_IDENTITY_MISMATCH")

            if row["lease_expires_at_ms"] <= now_ms:
                db.execute("ROLLBACK")
                return DurableDecision(False, "LEASE_EXPIRED")

            try:
                db.execute(
                    """
                    INSERT INTO completions (
                        task_id, generation, completion_key,
                        result_digest, completed_at_ms
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (task_id, generation, completion_key, result_digest.lower(), now_ms),
                )
            except sqlite3.IntegrityError:
                db.execute("ROLLBACK")
                return DurableDecision(False, "COMPLETION_KEY_REUSED")

            db.execute(
                """
                UPDATE tasks
                SET status = ?,
                    worker_id = NULL,
                    lease_id = NULL,
                    lease_expires_at_ms = NULL
                WHERE task_id = ? AND generation = ?
                """,
                (DurableTaskStatus.COMPLETED.value, task_id, generation),
            )
            updated = db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            db.execute("COMMIT")
            return DurableDecision(True, "TASK_COMPLETED", self._row_to_task(updated))

    def cancel(
        self,
        task_id: str,
        *,
        now_ms: int,
        authorization_verified: bool,
        claimed_coordinator_id: str | None = None,
        claimed_epoch: int | None = None,
        message_id: str = "cancel",
    ) -> DurableDecision:
        if not authorization_verified:
            return DurableDecision(False, "AUTHORIZATION_REQUIRED")

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            epoch_code = self._epoch_rejection(
                db,
                task_id=task_id,
                claimed_coordinator_id=claimed_coordinator_id,
                claimed_epoch=claimed_epoch,
                message_id=message_id,
                generation=1,
            )
            if epoch_code:
                db.execute("ROLLBACK")
                return DurableDecision(False, epoch_code)

            row = db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                return DurableDecision(False, "UNKNOWN_TASK")

            if row["status"] == DurableTaskStatus.COMPLETED.value:
                db.execute("ROLLBACK")
                return DurableDecision(False, "TASK_ALREADY_COMPLETED")

            if row["status"] == DurableTaskStatus.CANCELLED.value:
                db.execute("COMMIT")
                return DurableDecision(True, "ALREADY_CANCELLED", self._row_to_task(row))

            db.execute(
                """
                UPDATE tasks
                SET status = ?,
                    generation = generation + 1,
                    worker_id = NULL,
                    lease_id = NULL,
                    lease_expires_at_ms = NULL
                WHERE task_id = ?
                """,
                (DurableTaskStatus.CANCELLED.value, task_id),
            )
            updated = db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            db.execute("COMMIT")
            return DurableDecision(True, "TASK_CANCELLED", self._row_to_task(updated))
