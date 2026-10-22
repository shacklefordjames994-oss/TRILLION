from dataclasses import dataclass
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class WorkerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    task_type: str
    payload_digest: str
    priority: int = 0


@dataclass(frozen=True)
class TaskLease:
    lease_id: str
    task_id: str
    worker_id: str
    issued_at_ms: int
    expires_at_ms: int
    generation: int


@dataclass(frozen=True)
class TaskSnapshot:
    task: TaskSpec
    status: TaskStatus
    lease: TaskLease | None
    generation: int
    reason: str


@dataclass(frozen=True)
class CoordinationDecision:
    accepted: bool
    reason: str
    snapshot: TaskSnapshot | None = None
    physical_execution_authorized: bool = False
