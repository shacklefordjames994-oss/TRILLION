import hashlib
import json

from optimus_swarm.command_models import CommandEnvelope, EvidenceClass


def canonical_payload(payload: dict) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def payload_digest(payload: dict) -> str:
    return hashlib.sha256(canonical_payload(payload)).hexdigest()


def validate_command_shape(
    command: CommandEnvelope,
    *,
    now_ms: int,
    max_lifetime_ms: int = 30_000,
    max_clock_skew_ms: int = 2_000,
) -> tuple[bool, str]:
    if not all(
        isinstance(value, str) and value.strip()
        for value in (command.command_id, command.coordinator_id, command.task_id, command.worker_id, command.lease_id)
    ):
        return False, "INVALID_IDENTITY"

    if command.coordinator_epoch < 1 or command.generation < 1:
        return False, "INVALID_EPOCH_OR_GENERATION"

    if command.issued_at_ms < 0 or now_ms < 0:
        return False, "INVALID_TIMESTAMP"

    if command.expires_at_ms <= command.issued_at_ms:
        return False, "INVALID_EXPIRY"

    if command.issued_at_ms > now_ms + max_clock_skew_ms:
        return False, "COMMAND_FROM_FUTURE"

    if command.expires_at_ms <= now_ms:
        return False, "COMMAND_EXPIRED"

    if command.expires_at_ms - command.issued_at_ms > max_lifetime_ms:
        return False, "COMMAND_LIFETIME_TOO_LONG"

    if command.evidence_class != EvidenceClass.SIMULATED:
        return False, "EVIDENCE_CLASS_NOT_ALLOWED"

    if not isinstance(command.payload, dict):
        return False, "INVALID_PAYLOAD"

    try:
        actual_digest = payload_digest(command.payload)
    except (TypeError, ValueError, OverflowError):
        return False, "NON_CANONICAL_PAYLOAD"

    if actual_digest != command.payload_digest.lower():
        return False, "PAYLOAD_DIGEST_MISMATCH"

    if not command.signature_verified:
        return False, "SIGNATURE_NOT_VERIFIED"

    return True, "SHAPE_VALID"
