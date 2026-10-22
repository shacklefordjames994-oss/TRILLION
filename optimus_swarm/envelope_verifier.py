from dataclasses import dataclass
import base64
import binascii

from cryptography.exceptions import InvalidSignature

from optimus_swarm.signed_envelope import SignedEnvelope, canonical_bytes, digest_hex


@dataclass(frozen=True)
class VerificationResult:
    accepted: bool
    reason_codes: tuple[str, ...]
    physical_execution_authorized: bool = False


def verify_envelope(
    envelope: SignedEnvelope,
    *,
    trusted_keys: dict[str, dict],
    now_ms: int,
    max_lifetime_ms: int = 60_000,
    max_clock_skew_ms: int = 2_000,
) -> VerificationResult:
    reasons = []

    if envelope.schema_version != "1.0":
        reasons.append("UNSUPPORTED_SCHEMA")

    if not envelope.message_id or not envelope.source_id or not envelope.key_id:
        reasons.append("MISSING_IDENTITY_FIELDS")

    if envelope.evidence_class not in {"SIMULATED", "OBSERVED", "INFERRED"}:
        reasons.append("INVALID_EVIDENCE_CLASS")

    if (
        not isinstance(envelope.sequence_number, int)
        or isinstance(envelope.sequence_number, bool)
        or envelope.sequence_number < 1
    ):
        reasons.append("INVALID_SEQUENCE_NUMBER")

    if envelope.created_at_ms <= 0:
        reasons.append("INVALID_CREATION_TIME")
    elif envelope.created_at_ms > now_ms + max_clock_skew_ms:
        reasons.append("CREATION_TIME_IN_FUTURE")

    lifetime = envelope.expires_at_ms - envelope.created_at_ms
    if lifetime <= 0 or lifetime > max_lifetime_ms:
        reasons.append("INVALID_ENVELOPE_LIFETIME")

    if now_ms > envelope.expires_at_ms:
        reasons.append("ENVELOPE_EXPIRED")

    try:
        payload_digest = digest_hex(canonical_bytes(envelope.payload))
        if payload_digest != envelope.payload_digest:
            reasons.append("PAYLOAD_DIGEST_MISMATCH")
    except (TypeError, ValueError):
        reasons.append("PAYLOAD_NOT_CANONICAL_JSON")

    key_record = trusted_keys.get(envelope.key_id)
    if not key_record:
        reasons.append("UNKNOWN_KEY_ID")
    else:
        if key_record.get("source_id") != envelope.source_id:
            reasons.append("KEY_SOURCE_MISMATCH")
        if key_record.get("revoked", True):
            reasons.append("KEY_REVOKED_OR_NOT_ACTIVE")

        public_key = key_record.get("public_key")
        if public_key is None:
            reasons.append("PUBLIC_KEY_MISSING")
        else:
            try:
                signature = base64.b64decode(envelope.signature_b64, validate=True)
                public_key.verify(signature, canonical_bytes(envelope.signed_fields()))
            except (InvalidSignature, ValueError, TypeError, binascii.Error):
                reasons.append("SIGNATURE_INVALID")

    return VerificationResult(
        accepted=not reasons,
        reason_codes=tuple(reasons),
        physical_execution_authorized=False,
    )
