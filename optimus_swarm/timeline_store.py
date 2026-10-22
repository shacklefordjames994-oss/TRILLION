from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

from optimus_swarm.timeline_models import TimelineEntry, TimelineEvent


class TimelineRejected(ValueError):
    pass


class TimelineIntegrityError(RuntimeError):
    pass


def _normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise TimelineRejected("Non-finite number in event")
        return value
    raise TimelineRejected(f"Unsupported event value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _event_dict(event: TimelineEvent) -> dict[str, Any]:
    return _normalize(asdict(event))


class TimelineStore:
    """
    SQLite event history for inspection and replay.

    Append-only is an application policy, not a tamper-proof guarantee.
    This store cannot authenticate sensor sources or authorize actions.
    """

    VALID_TYPES = {
        "SENSOR_INPUT",
        "PERCEPTION_RESULT",
        "WORLD_MODEL_UPDATE",
        "REASONING_SUMMARY",
        "ACTION_PROPOSAL",
        "AUTHORITY_STATE",
        "FEED_STATUS",
        "SYSTEM_FAULT",
    }
    VALID_CLASSES = {"OBSERVED", "INFERRED", "SIMULATED", "UNKNOWN"}

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 5000")
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS timeline_events (
                    event_id TEXT PRIMARY KEY,
                    robot_id TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    event_time_ms INTEGER NOT NULL,
                    received_at_ms INTEGER NOT NULL,
                    clock_domain TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    evidence_class TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    event_digest TEXT NOT NULL,
                    UNIQUE(robot_id, sequence_number)
                )
                """
            )
            db.execute(
                """
                CREATE INDEX IF NOT EXISTS timeline_order_idx
                ON timeline_events(received_at_ms, robot_id, sequence_number)
                """
            )

    def append(self, event: TimelineEvent) -> str:
        data = _event_dict(event)

        for field in ("event_id", "robot_id", "clock_domain", "source_id", "source_ref"):
            value = data.get(field)
            if not isinstance(value, str) or not value.strip():
                raise TimelineRejected(f"Invalid {field}")

        for field in ("sequence_number", "event_time_ms", "received_at_ms", "schema_version"):
            value = data.get(field)
            if type(value) is not int or value < 0:
                raise TimelineRejected(f"Invalid {field}")

        if data["sequence_number"] == 0:
            raise TimelineRejected("sequence_number must start at 1 or higher")

        if data["schema_version"] != 1:
            raise TimelineRejected("Unsupported schema version")

        if data["event_type"] not in self.VALID_TYPES:
            raise TimelineRejected("Unsupported event_type")

        if data["evidence_class"] not in self.VALID_CLASSES:
            raise TimelineRejected("Unsupported evidence_class")

        payload_json = canonical_json(data["payload"])
        digest = digest_json(data)

        try:
            with self._connect() as db:
                db.execute(
                    """
                    INSERT INTO timeline_events (
                        event_id, robot_id, sequence_number,
                        event_time_ms, received_at_ms, clock_domain,
                        event_type, evidence_class, source_id, source_ref,
                        schema_version, payload_json, event_digest
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["event_id"],
                        data["robot_id"],
                        data["sequence_number"],
                        data["event_time_ms"],
                        data["received_at_ms"],
                        data["clock_domain"],
                        data["event_type"],
                        data["evidence_class"],
                        data["source_id"],
                        data["source_ref"],
                        data["schema_version"],
                        payload_json,
                        digest,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise TimelineRejected("Duplicate event ID or robot sequence number") from exc

        return digest

    def _decode_row(self, row: sqlite3.Row) -> dict[str, Any]:
        event = {
            "event_id": row["event_id"],
            "robot_id": row["robot_id"],
            "sequence_number": row["sequence_number"],
            "event_time_ms": row["event_time_ms"],
            "received_at_ms": row["received_at_ms"],
            "clock_domain": row["clock_domain"],
            "event_type": row["event_type"],
            "evidence_class": row["evidence_class"],
            "source_id": row["source_id"],
            "source_ref": row["source_ref"],
            "schema_version": row["schema_version"],
            "payload": json.loads(row["payload_json"]),
        }
        actual = digest_json(event)
        if not hmac.compare_digest(actual, row["event_digest"]):
            raise TimelineIntegrityError(f"Event digest mismatch: {row['event_id']}")
        event["event_digest"] = row["event_digest"]
        return event

    def replay(
        self,
        *,
        start_received_at_ms: int = 0,
        end_received_at_ms: int | None = None,
        robot_id: str | None = None,
        limit: int = 1000,
    ) -> list[TimelineEntry]:
        if type(start_received_at_ms) is not int or start_received_at_ms < 0:
            raise ValueError("Invalid start timestamp")
        if end_received_at_ms is not None and (
            type(end_received_at_ms) is not int or end_received_at_ms < start_received_at_ms
        ):
            raise ValueError("Invalid end timestamp")
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("limit must be between 1 and 10000")

        query = "SELECT * FROM timeline_events WHERE received_at_ms >= ?"
        args: list[Any] = [start_received_at_ms]
        if end_received_at_ms is not None:
            query += " AND received_at_ms <= ?"
            args.append(end_received_at_ms)
        if robot_id is not None:
            query += " AND robot_id = ?"
            args.append(robot_id)
        query += " ORDER BY received_at_ms, robot_id, sequence_number LIMIT ?"
        args.append(limit)

        with self._connect() as db:
            rows = db.execute(query, args).fetchall()

        entries: list[TimelineEntry] = []
        previous_by_robot: dict[str, dict[str, Any]] = {}
        for row in rows:
            event = self._decode_row(row)
            rid = event["robot_id"]
            previous = previous_by_robot.get(rid)
            if previous is None and event["sequence_number"] > 1:
                entries.append(
                    TimelineEntry(
                        kind="SEQUENCE_GAP",
                        event=None,
                        message=(
                            f"{rid}: replay begins at sequence {event['sequence_number']}; "
                            "earlier events are outside this replay window or unavailable."
                        ),
                    )
                )
            elif previous is not None:
                expected = previous["sequence_number"] + 1
                actual_sequence = event["sequence_number"]
                if actual_sequence > expected:
                    entries.append(
                        TimelineEntry(
                            kind="SEQUENCE_GAP",
                            event=None,
                            message=f"{rid}: missing sequence numbers {expected} through {actual_sequence - 1}.",
                        )
                    )
                elif actual_sequence < expected:
                    entries.append(
                        TimelineEntry(
                            kind="ORDER_ANOMALY",
                            event=None,
                            message=f"{rid}: sequence ordering anomaly; expected {expected}, found {actual_sequence}.",
                        )
                    )
                if event["event_time_ms"] < previous["event_time_ms"]:
                    entries.append(
                        TimelineEntry(
                            kind="CLOCK_REGRESSION",
                            event=None,
                            message=f"{rid}: source event time regressed relative to the previous replayed event.",
                        )
                    )
            entries.append(TimelineEntry(kind="EVENT", event=event, message="Historical event; not a live sensor feed."))
            previous_by_robot[rid] = event
        return entries
