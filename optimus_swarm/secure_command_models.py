from dataclasses import dataclass
from enum import Enum
from typing import Any


class EvidenceClass(str, Enum):
    SIMULATED = "SIMULATED"
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"


class DecisionStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class SignedCommand:
    schema_version: int
    command_id: str
    source_id: str
    key_id: str
    coordinator_id: str
    coordinator_epoch: int
    task_id: str
    worker_id: str
    lease_id: str
    generation: int
    issued_at_ms: int
    expires_at_ms: int
    evidence_class: EvidenceClass
    payload: dict[str, Any]
    payload_digest: str
    signature_b64: str


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    code: str
    source_id: str = ""
    key_id: str = ""


@dataclass(frozen=True)
class CommandDecision:
    status: DecisionStatus
    code: str
    command_id: str
    simulation_permitted: bool = False
    physical_execution_authorized: bool = False
