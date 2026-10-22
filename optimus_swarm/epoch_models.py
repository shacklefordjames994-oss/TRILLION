from dataclasses import dataclass
from enum import Enum


class EpochStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class CoordinatorEpoch:
    coordinator_id: str
    epoch: int
    started_at_ms: int


@dataclass(frozen=True)
class EpochDecision:
    accepted: bool
    code: str
    epoch: int
    physical_execution_authorized: bool = False


@dataclass(frozen=True)
class RecoveryItem:
    task_id: str
    prior_generation: int
    prior_worker_id: str | None
    prior_lease_id: str | None
    reason: str


@dataclass(frozen=True)
class StartupRecoveryReport:
    status: EpochStatus
    epoch: int
    items: tuple[RecoveryItem, ...]
    physical_execution_authorized: bool = False
