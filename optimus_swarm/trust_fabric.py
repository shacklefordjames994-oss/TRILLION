from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import math
import re
from typing import Any

HEX_256 = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return sha256(value).hexdigest()


@dataclass(frozen=True)
class SharedExperience:
    experience_id: str
    source_robot_id: str
    source_type: str
    simulator_version: str
    model_version: str
    created_at_ms: int
    experience_type: str
    validation_status: str
    confidence: float
    payload: dict[str, Any]
    payload_digest: str = ""

    def payload_for_digest(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("payload_digest", None)
        return data

    def calculate_digest(self) -> str:
        return sha256_hex(canonical_json(self.payload_for_digest()))

    def sealed(self) -> "SharedExperience":
        return replace(self, payload_digest=self.calculate_digest())


@dataclass(frozen=True)
class TrustDecision:
    accepted: bool
    reason_codes: tuple[str, ...]
    experience_digest: str
    physical_execution_authorized: bool = False


@dataclass(frozen=True)
class TrustPolicy:
    max_age_ms: int = 60_000
    allowed_source_types: frozenset[str] = frozenset({"SIMULATED_RENDER", "SIMULATED_SCENE_GRAPH"})
    allowed_experience_types: frozenset[str] = frozenset(
        {"OBJECT_LOCALIZATION", "SPATIAL_RELATION", "TASK_OUTCOME"}
    )
    minimum_confidence: float = 0.0
    maximum_payload_bytes: int = 64_000


def validate_shared_experience(
    experience: SharedExperience,
    *,
    now_ms: int,
    trusted_source_ids: set[str],
    policy: TrustPolicy = TrustPolicy(),
) -> TrustDecision:
    reasons: list[str] = []

    # Authenticate neither the sender nor the message here.
    # This registry is a local allowlist, not cryptographic identity.
    if experience.source_robot_id not in trusted_source_ids:
        reasons.append("UNTRUSTED_SOURCE_ID")

    if experience.source_type not in policy.allowed_source_types:
        reasons.append("SOURCE_TYPE_NOT_ALLOWED")

    if experience.experience_type not in policy.allowed_experience_types:
        reasons.append("EXPERIENCE_TYPE_NOT_ALLOWED")

    if experience.validation_status != "VALIDATED":
        reasons.append("EXPERIENCE_NOT_VALIDATED")

    if not experience.experience_id:
        reasons.append("MISSING_EXPERIENCE_ID")

    if not experience.simulator_version or not experience.model_version:
        reasons.append("MISSING_VERSION_METADATA")

    if experience.created_at_ms <= 0 or now_ms < experience.created_at_ms:
        reasons.append("INVALID_TIMESTAMP")
    elif now_ms - experience.created_at_ms > policy.max_age_ms:
        reasons.append("STALE_EXPERIENCE")

    if (
        not isinstance(experience.confidence, (int, float))
        or isinstance(experience.confidence, bool)
        or not math.isfinite(experience.confidence)
        or not 0.0 <= experience.confidence <= 1.0
    ):
        reasons.append("INVALID_CONFIDENCE")
    elif experience.confidence < policy.minimum_confidence:
        reasons.append("CONFIDENCE_BELOW_POLICY")

    try:
        encoded = canonical_json(experience.payload_for_digest())
        if len(encoded) > policy.maximum_payload_bytes:
            reasons.append("PAYLOAD_TOO_LARGE")
    except (TypeError, ValueError):
        encoded = b""
        reasons.append("PAYLOAD_NOT_CANONICAL_JSON")

    calculated = sha256_hex(encoded) if encoded else ""

    if not HEX_256.fullmatch(experience.payload_digest or ""):
        reasons.append("MISSING_OR_INVALID_DIGEST")
    elif experience.payload_digest != calculated:
        reasons.append("DIGEST_MISMATCH")

    return TrustDecision(
        accepted=not reasons,
        reason_codes=tuple(reasons),
        experience_digest=calculated,
        physical_execution_authorized=False,
    )
