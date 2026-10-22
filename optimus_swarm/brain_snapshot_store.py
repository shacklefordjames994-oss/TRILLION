from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class SnapshotRejected(ValueError):
    """Snapshot failed validation or violated storage policy."""


class SnapshotIntegrityError(RuntimeError):
    """Stored snapshot failed its integrity check."""


def to_json_value(value: Any) -> Any:
    """Convert supported Python values to deterministic JSON values."""
    if isinstance(value, Enum):
        return value.value

    if is_dataclass(value) and not isinstance(value, type):
        return to_json_value(asdict(value))

    if isinstance(value, dict):
        return {str(key): to_json_value(item) for key, item in value.items()}

    if isinstance(value, (tuple, list)):
        return [to_json_value(item) for item in value]

    if value is None or isinstance(value, (str, int, bool)):
        return value

    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise SnapshotRejected("Non-finite number")
        return value

    raise SnapshotRejected(f"Unsupported serialization type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        to_json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class BrainSnapshotStore:
    """
    Durable snapshot history for inspection.

    validator(snapshot, now_ms) must return an object with:
      - accepted: bool
      - issues: iterable, if available

    This store does not authenticate sensors, prove truth, or
    authorize physical execution. A digest is not a signature.
    """

    def __init__(self, db_path: str | Path, validator: Callable[[Any, int], Any]) -> None:
        self.db_path = str(db_path)
        self.validator = validator
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    created_at_ms INTEGER NOT NULL,
                    authority_revision INTEGER NOT NULL,
                    canonical_payload TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    stored_at_ms INTEGER NOT NULL
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_brain_snapshots_created
                ON brain_snapshots(created_at_ms DESC)
                """
            )

    def publish(self, snapshot: Any, *, now_ms: int) -> str:
        """Validate and store a snapshot. Duplicate IDs are rejected."""
        result = self.validator(snapshot, now_ms=now_ms)

        if not getattr(result, "accepted", False):
            issues = getattr(result, "issues", ())
            raise SnapshotRejected("Snapshot validation failed: " + "; ".join(str(issue) for issue in issues))

        snapshot_id = getattr(snapshot, "snapshot_id", None)
        created_at_ms = getattr(snapshot, "created_at_ms", None)
        authority_revision = getattr(snapshot, "authority_revision", None)

        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise SnapshotRejected("Missing snapshot_id")

        for name, value in (
            ("created_at_ms", created_at_ms),
            ("authority_revision", authority_revision),
            ("now_ms", now_ms),
        ):
            if type(value) is not int or value < 0:
                raise SnapshotRejected(f"Invalid {name}")

        if getattr(snapshot, "physical_execution_enabled", True) is not False:
            raise SnapshotRejected("Physical execution must remain disabled")

        payload = canonical_json(snapshot)
        digest = sha256_hex(payload)

        try:
            with self._connect() as db:
                db.execute(
                    """
                    INSERT INTO brain_snapshots (
                        snapshot_id,
                        created_at_ms,
                        authority_revision,
                        canonical_payload,
                        payload_sha256,
                        stored_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (snapshot_id, created_at_ms, authority_revision, payload, digest, now_ms),
                )
        except sqlite3.IntegrityError as exc:
            raise SnapshotRejected("Duplicate snapshot_id or storage constraint failure") from exc

        return digest

    def get(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM brain_snapshots
                WHERE snapshot_id = ?
                """,
                (snapshot_id,),
            ).fetchone()

        if row is None:
            return None

        payload = row["canonical_payload"]
        actual = sha256_hex(payload)

        if not hmac.compare_digest(actual, row["payload_sha256"]):
            raise SnapshotIntegrityError(f"Digest mismatch for {snapshot_id}")

        result = json.loads(payload)
        result["_store_metadata"] = {
            "stored_at_ms": row["stored_at_ms"],
            "payload_sha256": row["payload_sha256"],
            "integrity_check": "DIGEST_MATCH",
        }
        return result

    def latest(self) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT snapshot_id FROM brain_snapshots
                ORDER BY created_at_ms DESC, snapshot_id DESC
                LIMIT 1
                """
            ).fetchone()

        return self.get(row["snapshot_id"]) if row else None

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit must be an integer from 1 to 500")

        with self._connect() as db:
            rows = db.execute(
                """
                SELECT snapshot_id
                FROM brain_snapshots
                ORDER BY created_at_ms DESC, snapshot_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        result = []
        for row in rows:
            item = self.get(row["snapshot_id"])
            if item is not None:
                result.append(item)
        return result
