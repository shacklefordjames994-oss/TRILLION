from dataclasses import dataclass
from enum import Enum


class EvidenceClass(str, Enum):
    SIMULATED = "SIMULATED"
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"


class CommandStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class CommandEnvelope:
    command_id: str
    coordinator_id: str
    coordinator_epoch: int
    task_id: str
    worker_id: str
    lease_id: str
    generation: int
    issued_at_ms: int
    expires_at_ms: int
    evidence_class: EvidenceClass
    payload: dict
    payload_digest: str
    signature_verified: bool


@dataclass(frozen=True)
class CommandDecision:
    status: CommandStatus
    code: str
    command_id: str
    simulation_permitted: bool
    physical_execution_authorized: bool = False
