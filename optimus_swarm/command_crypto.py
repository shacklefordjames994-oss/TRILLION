import base64
import hashlib
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from optimus_swarm.secure_command_models import EvidenceClass, SignedCommand, VerificationResult


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_digest(payload: dict) -> str:
    return sha256_hex(canonical_json(payload))


def signed_fields(command: SignedCommand) -> dict:
    """Return every field covered by the digital signature."""
    return {
        "schema_version": command.schema_version,
        "command_id": command.command_id,
        "source_id": command.source_id,
        "key_id": command.key_id,
        "coordinator_id": command.coordinator_id,
        "coordinator_epoch": command.coordinator_epoch,
        "task_id": command.task_id,
        "worker_id": command.worker_id,
        "lease_id": command.lease_id,
        "generation": command.generation,
        "issued_at_ms": command.issued_at_ms,
        "expires_at_ms": command.expires_at_ms,
        "evidence_class": command.evidence_class.value,
        "payload": command.payload,
        "payload_digest": command.payload_digest,
    }


def generate_keypair() -> tuple[bytes, bytes]:
    """Return raw private and public Ed25519 key bytes. Test harness only."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_bytes, public_bytes


def sign_command(
    *,
    private_key_bytes: bytes,
    command_id: str,
    source_id: str,
    key_id: str,
    coordinator_id: str,
    coordinator_epoch: int,
    task_id: str,
    worker_id: str,
    lease_id: str,
    generation: int,
    issued_at_ms: int,
    expires_at_ms: int,
    payload: dict,
) -> SignedCommand:
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    unsigned = SignedCommand(
        schema_version=1,
        command_id=command_id,
        source_id=source_id,
        key_id=key_id,
        coordinator_id=coordinator_id,
        coordinator_epoch=coordinator_epoch,
        task_id=task_id,
        worker_id=worker_id,
        lease_id=lease_id,
        generation=generation,
        issued_at_ms=issued_at_ms,
        expires_at_ms=expires_at_ms,
        evidence_class=EvidenceClass.SIMULATED,
        payload=payload,
        payload_digest=payload_digest(payload),
        signature_b64="",
    )
    signature = private_key.sign(canonical_json(signed_fields(unsigned)))
    return SignedCommand(
        **{**unsigned.__dict__, "signature_b64": base64.b64encode(signature).decode("ascii")}
    )


def verify_signature(command: SignedCommand, public_key_bytes: bytes) -> VerificationResult:
    try:
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        signature = base64.b64decode(command.signature_b64, validate=True)
        if command.payload_digest != payload_digest(command.payload):
            return VerificationResult(False, "PAYLOAD_DIGEST_MISMATCH")
        public_key.verify(signature, canonical_json(signed_fields(command)))
        return VerificationResult(True, "SIGNATURE_VALID", command.source_id, command.key_id)
    except (InvalidSignature, ValueError, TypeError, KeyError):
        return VerificationResult(False, "SIGNATURE_INVALID")
    except Exception:
        return VerificationResult(False, "VERIFICATION_ERROR")
