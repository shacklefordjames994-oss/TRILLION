from dataclasses import dataclass
from typing import Mapping
import base64
import json
import sqlite3
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)


def canonical_bytes(value: dict) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


@dataclass(frozen=True)
class SignedPolicy:
    key_id: str
    policy_id: str
    version: int
    issued_at: int
    expires_at: int
    mode: str
    approved_actions: tuple[str, ...]
    signature_b64: str

    def unsigned_payload(self) -> dict:
        return {
            "key_id": self.key_id,
            "policy_id": self.policy_id,
            "version": self.version,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "mode": self.mode,
            "approved_actions": list(self.approved_actions),
        }


def sign_policy(
    private_key: Ed25519PrivateKey,
    key_id: str,
    policy_id: str,
    version: int,
    issued_at: int,
    expires_at: int,
    approved_actions: tuple[str, ...],
) -> SignedPolicy:
    if version < 1 or expires_at <= issued_at:
        raise ValueError("Invalid policy version or validity interval.")

    if not key_id or not policy_id:
        raise ValueError("key_id and policy_id are required.")

    if len(set(approved_actions)) != len(approved_actions):
        raise ValueError("Duplicate actions are not allowed.")

    if any(not isinstance(a, str) or not a.strip() for a in approved_actions):
        raise ValueError("Every action must be a non-empty string.")

    payload = {
        "key_id": key_id,
        "policy_id": policy_id,
        "version": version,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "mode": "SIMULATION_ONLY",
        "approved_actions": list(approved_actions),
    }
    signature = private_key.sign(canonical_bytes(payload))

    return SignedPolicy(
        key_id=key_id,
        policy_id=policy_id,
        version=version,
        issued_at=issued_at,
        expires_at=expires_at,
        mode="SIMULATION_ONLY",
        approved_actions=approved_actions,
        signature_b64=base64.b64encode(signature).decode("ascii"),
    )


def public_key_bytes(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw,
    )


class PolicyVerifier:
    """
    Verifies policy signatures and stores the highest accepted version
    per policy ID in SQLite.

    The database itself must be protected against rollback or replacement
    in production, for example with hardware-backed monotonic state or
    a remotely anchored version record.
    """

    def __init__(
        self,
        trusted_keys: Mapping[str, Ed25519PublicKey],
        database_path: str,
    ):
        self._trusted_keys = dict(trusted_keys)
        self._db = sqlite3.connect(database_path)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS policy_versions (
                policy_id TEXT PRIMARY KEY,
                highest_version INTEGER NOT NULL
            )
            """
        )
        self._db.commit()

    def verify_and_accept(
        self,
        policy: SignedPolicy,
        now: int | None = None,
    ) -> tuple[bool, str]:
        now = int(time.time()) if now is None else now

        key = self._trusted_keys.get(policy.key_id)
        if key is None:
            return False, "UNTRUSTED_SIGNING_KEY"

        if policy.mode != "SIMULATION_ONLY":
            return False, "MODE_NOT_ALLOWED"

        if policy.version < 1 or policy.expires_at <= policy.issued_at:
            return False, "INVALID_POLICY_METADATA"

        if policy.issued_at > now or policy.expires_at <= now:
            return False, "POLICY_NOT_CURRENTLY_VALID"

        if len(set(policy.approved_actions)) != len(policy.approved_actions):
            return False, "DUPLICATE_POLICY_ACTION"

        if any(not isinstance(a, str) or not a.strip() for a in policy.approved_actions):
            return False, "INVALID_POLICY_ACTION"

        try:
            signature = base64.b64decode(
                policy.signature_b64,
                validate=True,
            )
            key.verify(signature, canonical_bytes(policy.unsigned_payload()))
        except (InvalidSignature, ValueError, TypeError):
            return False, "SIGNATURE_INVALID"

        try:
            with self._db:
                row = self._db.execute(
                    "SELECT highest_version FROM policy_versions "
                    "WHERE policy_id = ?",
                    (policy.policy_id,),
                ).fetchone()

                if row and policy.version < row[0]:
                    return False, "POLICY_ROLLBACK_REJECTED"

                if row and policy.version == row[0]:
                    return False, "POLICY_VERSION_ALREADY_ACCEPTED"

                self._db.execute(
                    """
                    INSERT INTO policy_versions(policy_id, highest_version)
                    VALUES(?, ?)
                    ON CONFLICT(policy_id)
                    DO UPDATE SET highest_version = excluded.highest_version
                    """,
                    (policy.policy_id, policy.version),
                )
        except sqlite3.Error:
            return False, "VERSION_STORE_UNAVAILABLE"

        return True, "POLICY_ACCEPTED"

    def close(self):
        self._db.close()
