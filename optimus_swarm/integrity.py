from dataclasses import dataclass, asdict
import hashlib
import hmac
import json
import time

GENESIS = "0" * 64


def canonical_json(value: dict) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


@dataclass(frozen=True)
class AuditRecord:
    sequence: int
    timestamp_ns: int
    actor_id: str
    event_type: str
    reason: str
    previous_hash: str
    record_hash: str
    mac: str


class TamperEvidentLedger:
    """
    Detects record modification, reordering, and many insertions.
    Not independently tamper-proof: protect the key and anchor
    checkpoints outside this process.
    """

    def __init__(self, hmac_key: bytes):
        if not isinstance(hmac_key, bytes) or len(hmac_key) < 32:
            raise ValueError("Use an externally managed key of 32+ bytes.")
        self._key = hmac_key
        self._records: list[AuditRecord] = []

    def append(self, actor_id: str, event_type: str, reason: str):
        if not actor_id or not event_type or not reason:
            raise ValueError("Actor, event type, and reason are required.")

        previous = self._records[-1].record_hash if self._records else GENESIS
        body = {
            "sequence": len(self._records) + 1,
            "timestamp_ns": time.time_ns(),
            "actor_id": actor_id,
            "event_type": event_type,
            "reason": reason,
            "previous_hash": previous,
        }

        record_hash = hashlib.sha256(canonical_json(body)).hexdigest()
        mac = hmac.new(
            self._key,
            record_hash.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

        record = AuditRecord(
            **body,
            record_hash=record_hash,
            mac=mac,
        )
        self._records.append(record)
        return record

    def verify(self) -> bool:
        previous = GENESIS

        for index, record in enumerate(self._records, start=1):
            if record.sequence != index:
                return False
            if record.previous_hash != previous:
                return False

            body = {
                "sequence": record.sequence,
                "timestamp_ns": record.timestamp_ns,
                "actor_id": record.actor_id,
                "event_type": record.event_type,
                "reason": record.reason,
                "previous_hash": record.previous_hash,
            }
            expected_hash = hashlib.sha256(canonical_json(body)).hexdigest()

            expected_mac = hmac.new(
                self._key,
                expected_hash.encode("ascii"),
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(record.record_hash, expected_hash):
                return False
            if not hmac.compare_digest(record.mac, expected_mac):
                return False

            previous = record.record_hash

        return True

    def export_records(self) -> list[dict]:
        return [asdict(record) for record in self._records]
