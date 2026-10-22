from dataclasses import dataclass
from enum import Enum


class EvidenceClass(str, Enum):
    SIMULATED = "SIMULATED"
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"


@dataclass(frozen=True)
class EvidenceClaim:
    evidence_class: EvidenceClass
    source_id: str
    source_record_digest: str
    explanation: str


@dataclass(frozen=True)
class EvidencePolicyResult:
    accepted: bool
    reason: str
    effective_class: EvidenceClass


def validate_evidence_claim(claim: EvidenceClaim, *, source_verified: bool) -> EvidencePolicyResult:
    if not claim.source_id or not claim.source_record_digest:
        return EvidencePolicyResult(False, "MISSING_PROVENANCE", claim.evidence_class)

    if not source_verified:
        return EvidencePolicyResult(False, "SOURCE_NOT_VERIFIED", claim.evidence_class)

    if not claim.explanation.strip():
        return EvidencePolicyResult(False, "MISSING_EXPLANATION", claim.evidence_class)

    # This validator preserves the declared class. It never upgrades
    # simulated or inferred data to observed evidence.
    return EvidencePolicyResult(True, "EVIDENCE_CLASS_PRESERVED", claim.evidence_class)
