from dataclasses import dataclass
from enum import Enum


class RecoveryStatus(str, Enum):
    READY = "READY"
    INHIBITED = "INHIBITED"
    INDETERMINATE = "INDETERMINATE"


class IssueSeverity(str, Enum):
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class WorkerHeartbeat:
    worker_id: str
    observed_at_ms: int
    sequence: int
    healthy: bool


@dataclass(frozen=True)
class ActiveLeaseRecord:
    lease_id: str
    task_id: str
    worker_id: str
    generation: int
    issued_at_ms: int
    expires_at_ms: int


@dataclass(frozen=True)
class RecoveryIssue:
    code: str
    severity: IssueSeverity
    detail: str


@dataclass(frozen=True)
class RecoveryReport:
    status: RecoveryStatus
    checked_at_ms: int
    issues: tuple[RecoveryIssue, ...]
    valid_lease_ids: tuple[str, ...]
    expired_lease_ids: tuple[str, ...]
    physical_execution_authorized: bool = False
