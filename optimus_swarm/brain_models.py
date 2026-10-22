from dataclasses import dataclass
from enum import Enum
from typing import Any


class EvidenceClass(str, Enum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    SIMULATED = "SIMULATED"
    UNKNOWN = "UNKNOWN"


class FeedStatus(str, Enum):
    LIVE = "LIVE"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    INVALID = "INVALID"


class AuthorityState(str, Enum):
    LATCHED = "LATCHED"
    CLEAR = "CLEAR"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    evidence_class: EvidenceClass
    source_id: str
    captured_at_ms: int
    digest: str
    model_version: str = ""


@dataclass(frozen=True)
class VisualObject:
    object_id: str
    label: str
    evidence_class: EvidenceClass
    confidence: float | None
    position_m: tuple[float, float, float] | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class RobotView:
    robot_id: str
    feed_status: FeedStatus
    updated_at_ms: int
    pose_evidence_class: EvidenceClass
    pose_m: tuple[float, float, float] | None
    objects: tuple[VisualObject, ...]
    unknown_region_count: int


@dataclass(frozen=True)
class TaskView:
    task_id: str
    status: str
    proposed_action: str
    expected_outcome: str
    evidence_ids: tuple[str, ...]
    risk_flags: tuple[str, ...]


@dataclass(frozen=True)
class BrainSnapshot:
    snapshot_id: str
    created_at_ms: int
    robot_views: tuple[RobotView, ...]
    tasks: tuple[TaskView, ...]
    evidence: tuple[EvidenceRef, ...]
    authority_state: AuthorityState
    authority_revision: int
    physical_execution_enabled: bool = False
