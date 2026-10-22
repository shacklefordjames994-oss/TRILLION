import sqlite3


class ReplayGuard:
    """
    Local replay guard for verified envelopes.

    Use one persistent database per receiver trust domain, with
    suitable filesystem permissions and transactional storage.
    """

    def __init__(self, database_path: str = ":memory:"):
        self.db = sqlite3.connect(database_path, isolation_level=None, timeout=5.0)
        self.db.execute("PRAGMA busy_timeout = 5000")
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS replay_state (
                source_id TEXT NOT NULL,
                key_id TEXT NOT NULL,
                last_sequence INTEGER NOT NULL,
                PRIMARY KEY (source_id, key_id)
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_messages (
                message_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                key_id TEXT NOT NULL,
                sequence_number INTEGER NOT NULL
            )
            """
        )

    def reserve(
        self,
        *,
        source_id: str,
        key_id: str,
        message_id: str,
        sequence_number: int,
    ) -> tuple[bool, str]:
        if not source_id or not key_id or not message_id:
            return False, "MISSING_REPLAY_IDENTITY"

        if not isinstance(sequence_number, int) or isinstance(sequence_number, bool) or sequence_number < 1:
            return False, "INVALID_SEQUENCE_NUMBER"

        try:
            self.db.execute("BEGIN IMMEDIATE")

            seen = self.db.execute(
                "SELECT 1 FROM seen_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()

            if seen:
                self.db.execute("ROLLBACK")
                return False, "DUPLICATE_MESSAGE_ID"

            row = self.db.execute(
                """
                SELECT last_sequence FROM replay_state
                WHERE source_id = ? AND key_id = ?
                """,
                (source_id, key_id),
            ).fetchone()

            last = row[0] if row else 0

            if sequence_number <= last:
                self.db.execute("ROLLBACK")
                return False, "REPLAYED_OR_OUT_OF_ORDER_SEQUENCE"

            self.db.execute(
                """
                INSERT INTO replay_state(source_id, key_id, last_sequence)
                VALUES (?, ?, ?)
                ON CONFLICT(source_id, key_id)
                DO UPDATE SET last_sequence = excluded.last_sequence
                """,
                (source_id, key_id, sequence_number),
            )

            self.db.execute(
                """
                INSERT INTO seen_messages(
                    message_id, source_id, key_id, sequence_number
                ) VALUES (?, ?, ?, ?)
                """,
                (message_id, source_id, key_id, sequence_number),
            )

            self.db.execute("COMMIT")
            return True, "SEQUENCE_ACCEPTED"

        except sqlite3.Error:
            try:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            return False, "REPLAY_STORE_ERROR"

    def close(self):
        self.db.close()
