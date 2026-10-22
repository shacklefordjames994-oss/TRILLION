from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class AdaptiveEventLog:
    """Local SQLite audit journal; not a tamper-proof ledger."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS adaptive_events (
                    event_id TEXT PRIMARY KEY,
                    created_at_ms INTEGER NOT NULL,
                    policy_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_digest TEXT NOT NULL,
                    event_digest TEXT NOT NULL UNIQUE
                )
                """
            )

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5.0)
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def append(
        self,
        *,
        event_id: str,
        policy_version: str,
        input_snapshot: dict[str, Any],
        decision: dict[str, Any],
        evidence_ids: list[str],
    ) -> str:
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("event_id is required")
        if not isinstance(policy_version, str) or not policy_version.strip():
            raise ValueError("policy_version is required")
        if not all(isinstance(item, str) and item.strip() for item in evidence_ids):
            raise ValueError("evidence_ids must contain non-empty strings")

        payload = {
            "schema_version": 1,
            "event_id": event_id,
            "created_at_ms": time.time_ns() // 1_000_000,
            "policy_version": policy_version,
            "input_snapshot": input_snapshot,
            "decision": decision,
            "evidence_ids": sorted(set(evidence_ids)),
            "physical_execution_permitted": False,
        }
        payload_json = canonical_json(payload)

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                """
                SELECT event_digest
                FROM adaptive_events
                ORDER BY rowid DESC LIMIT 1
                """
            ).fetchone()
            previous_digest = previous[0] if previous else "GENESIS"
            event_digest = hashlib.sha256(
                canonical_json({"previous_digest": previous_digest, "payload": payload}).encode("utf-8")
            ).hexdigest()
            db.execute(
                """
                INSERT INTO adaptive_events (
                    event_id, created_at_ms, policy_version,
                    payload_json, previous_digest, event_digest
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    payload["created_at_ms"],
                    policy_version,
                    payload_json,
                    previous_digest,
                    event_digest,
                ),
            )
        return event_digest


def publish_logged_decision(
    log: AdaptiveEventLog,
    *,
    event_id: str,
    policy_version: str,
    input_snapshot: dict[str, Any],
    decision: dict[str, Any],
    evidence_ids: list[str],
) -> dict[str, Any]:
    """Persist first. A failed write blocks use of the decision."""
    try:
        digest = log.append(
            event_id=event_id,
            policy_version=policy_version,
            input_snapshot=input_snapshot,
            decision=decision,
            evidence_ids=evidence_ids,
        )
    except Exception:
        return {
            "accepted": False,
            "response_grade": "G4_DATA_INVALID",
            "reason": "AUDIT_WRITE_FAILED",
            "event_digest": None,
            "physical_execution_permitted": False,
        }
    return {
        "accepted": True,
        "response_grade": decision.get("response_grade"),
        "event_digest": digest,
        "physical_execution_permitted": False,
    }
