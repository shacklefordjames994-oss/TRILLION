from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json
import sqlite3
from pathlib import Path
from typing import Any


class JournalError(RuntimeError):
    pass


class AssessmentStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INDETERMINATE = "INDETERMINATE"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StoredRun:
    run_id: str
    payload: dict[str, Any]
    payload_digest: str


@dataclass(frozen=True)
class StoredAssessment:
    assessment_id: str
    run_id: str
    run_digest: str
    status: AssessmentStatus
    reasons: tuple[str, ...]
    physical_execution_enabled: bool = False


class BenchmarkJournal:
    """Local SQLite journal. A stored assessment does not clear an inhibit or enable motion."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        try:
            with self._connect() as db:
                db.execute("PRAGMA foreign_keys = ON")
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS benchmark_runs (
                        run_id TEXT PRIMARY KEY,
                        payload_json TEXT NOT NULL,
                        payload_digest TEXT NOT NULL,
                        stored_at_utc TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS benchmark_assessments (
                        assessment_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        run_digest TEXT NOT NULL,
                        status TEXT NOT NULL,
                        reasons_json TEXT NOT NULL,
                        physical_execution_enabled INTEGER NOT NULL
                            DEFAULT 0 CHECK (physical_execution_enabled = 0),
                        FOREIGN KEY(run_id) REFERENCES benchmark_runs(run_id)
                    );
                    """
                )
        except sqlite3.Error as exc:
            raise JournalError("Evidence journal unavailable") from exc

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            db = sqlite3.connect(self.path, timeout=10)
        except sqlite3.Error as exc:
            raise JournalError("Evidence journal unavailable") from exc
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def store_run(self, run_id: str, payload: dict[str, Any], stored_at_utc: str) -> StoredRun:
        if not isinstance(run_id, str) or not run_id.strip():
            raise JournalError("Invalid run ID")
        if not isinstance(stored_at_utc, str) or not stored_at_utc.strip():
            raise JournalError("Missing storage timestamp")
        if not isinstance(payload, dict):
            raise JournalError("Run payload must be an object")
        if payload.get("physical_execution_enabled") is not False:
            raise JournalError("Physical execution must remain false")
        if payload.get("run_id") != run_id:
            raise JournalError("Run ID does not match payload")

        serialized = canonical_json(payload)
        payload_digest = sha256_text(serialized)
        try:
            with self._connect() as db:
                db.execute(
                    """
                    INSERT INTO benchmark_runs
                    (run_id, payload_json, payload_digest, stored_at_utc)
                    VALUES (?, ?, ?, ?)
                    """,
                    (run_id, serialized, payload_digest, stored_at_utc),
                )
        except JournalError:
            raise
        except sqlite3.IntegrityError as exc:
            raise JournalError("Duplicate run ID or journal constraint violation") from exc
        return StoredRun(run_id, payload, payload_digest)

    def read_run(self, run_id: str) -> StoredRun:
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT payload_json, payload_digest FROM benchmark_runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
        except JournalError:
            raise
        except sqlite3.Error as exc:
            raise JournalError("Evidence journal unavailable") from exc

        if row is None:
            raise JournalError("Run not found")

        actual_digest = sha256_text(row["payload_json"])
        stored_digest = row["payload_digest"]
        if len(actual_digest) != len(stored_digest) or not hmac.compare_digest(actual_digest, stored_digest):
            raise JournalError("Stored run digest mismatch")

        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError as exc:
            raise JournalError("Stored run JSON is invalid") from exc

        if not isinstance(payload, dict):
            raise JournalError("Stored run payload is not an object")
        if payload.get("run_id") != run_id:
            raise JournalError("Stored run ID mismatch")
        if payload.get("physical_execution_enabled") is not False:
            raise JournalError("Physical execution invariant violated")
        return StoredRun(run_id, payload, actual_digest)

    def append_assessment(
        self,
        assessment_id: str,
        run_id: str,
        expected_run_digest: str,
        status: AssessmentStatus,
        reasons: tuple[str, ...],
    ) -> StoredAssessment:
        if not isinstance(assessment_id, str) or not assessment_id.strip():
            raise JournalError("Invalid assessment ID")
        stored = self.read_run(run_id)
        if len(stored.payload_digest) != len(expected_run_digest) or not hmac.compare_digest(
            stored.payload_digest, expected_run_digest
        ):
            raise JournalError("Assessment references wrong run digest")

        try:
            with self._connect() as db:
                db.execute(
                    """
                    INSERT INTO benchmark_assessments
                    (assessment_id, run_id, run_digest, status, reasons_json, physical_execution_enabled)
                    VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (assessment_id, run_id, stored.payload_digest, status.value, canonical_json(list(reasons))),
                )
        except JournalError:
            raise
        except sqlite3.IntegrityError as exc:
            raise JournalError("Duplicate assessment ID or invalid run reference") from exc

        return StoredAssessment(assessment_id, run_id, stored.payload_digest, status, reasons, False)
