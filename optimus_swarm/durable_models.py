from dataclasses import dataclass
from enum import Enum


class DurableTaskStatus(str, Enum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class DurableTask:
    task_id: str
    payload_digest: str
    priority: int
    status: DurableTaskStatus
    generation: int
    worker_id: str | None
    lease_id: str | None
    lease_expires_at_ms: int | None


@dataclass(frozen=True)
class DurableDecision:
    accepted: bool
    code: str
    task: DurableTask | None = None
    physical_execution_authorized: bool = False
