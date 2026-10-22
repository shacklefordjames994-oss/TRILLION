import sqlite3
from contextlib import contextmanager
from pathlib import Path


class ReplayStoreError(RuntimeError):
    pass


class DurableReplayStore:
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
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS accepted_commands (
                        command_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        key_id TEXT NOT NULL,
                        coordinator_epoch INTEGER NOT NULL,
                        payload_digest TEXT NOT NULL,
                        accepted_at_ms INTEGER NOT NULL
                    )
                    """
                )
        except sqlite3.Error as exc:
            raise ReplayStoreError("REPLAY_STORE_INIT_FAILED") from exc

    def reserve(
        self,
        *,
        command_id: str,
        source_id: str,
        key_id: str,
        coordinator_epoch: int,
        payload_digest: str,
        now_ms: int,
    ) -> bool:
        """True means this command ID was reserved for the first time."""
        if not all((command_id, source_id, key_id, payload_digest)):
            raise ValueError("REPLAY_FIELDS_REQUIRED")
        if coordinator_epoch < 0 or now_ms < 0:
            raise ValueError("INVALID_REPLAY_METADATA")

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        """
                        INSERT INTO accepted_commands (
                            command_id, source_id, key_id,
                            coordinator_epoch, payload_digest,
                            accepted_at_ms
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (command_id, source_id, key_id, coordinator_epoch, payload_digest, now_ms),
                    )
                    connection.execute("COMMIT")
                    return True
                except sqlite3.IntegrityError:
                    connection.execute("ROLLBACK")
                    return False
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except (sqlite3.Error, OSError) as exc:
            raise ReplayStoreError("REPLAY_STORE_UNAVAILABLE") from exc
