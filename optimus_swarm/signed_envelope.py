from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import base64
import json
from typing import Any


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def digest_hex(data: bytes) -> str:
    return sha256(data).hexdigest()


@dataclass(frozen=True)
class SignedEnvelope:
    schema_version: str
    message_id: str
    source_id: str
    key_id: str
    sequence_number: int
    created_at_ms: int
    expires_at_ms: int
    evidence_class: str
    payload: dict[str, Any]
    payload_digest: str
    signature_b64: str

    def signed_fields(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "message_id": self.message_id,
            "source_id": self.source_id,
            "key_id": self.key_id,
            "sequence_number": self.sequence_number,
            "created_at_ms": self.created_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "evidence_class": self.evidence_class,
            "payload": self.payload,
            "payload_digest": self.payload_digest,
        }


def create_signed_envelope(
    *,
    private_key,
    message_id: str,
    source_id: str,
    key_id: str,
    sequence_number: int,
    created_at_ms: int,
    expires_at_ms: int,
    evidence_class: str,
    payload: dict[str, Any],
) -> SignedEnvelope:
    if not message_id or not source_id or not key_id:
        raise ValueError("message_id, source_id and key_id are required")

    if not isinstance(sequence_number, int) or isinstance(sequence_number, bool) or sequence_number < 1:
        raise ValueError("sequence_number must be a positive integer")

    if created_at_ms <= 0 or expires_at_ms <= created_at_ms:
        raise ValueError("invalid envelope time range")

    if evidence_class not in {"SIMULATED", "OBSERVED", "INFERRED"}:
        raise ValueError("unsupported evidence class")

    payload_digest = digest_hex(canonical_bytes(payload))
    unsigned = SignedEnvelope(
        schema_version="1.0",
        message_id=message_id,
        source_id=source_id,
        key_id=key_id,
        sequence_number=sequence_number,
        created_at_ms=created_at_ms,
        expires_at_ms=expires_at_ms,
        evidence_class=evidence_class,
        payload=payload,
        payload_digest=payload_digest,
        signature_b64="",
    )
    signature = private_key.sign(canonical_bytes(unsigned.signed_fields()))
    return SignedEnvelope(
        **{
            **unsigned.__dict__,
            "signature_b64": base64.b64encode(signature).decode("ascii"),
        }
    )
