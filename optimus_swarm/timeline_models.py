from dataclasses import dataclass
from enum import Enum
from typing import Any


class TimelineEvidenceClass(str, Enum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    SIMULATED = "SIMULATED"
    UNKNOWN = "UNKNOWN"


class TimelineEventType(str, Enum):
    SENSOR_INPUT = "SENSOR_INPUT"
    PERCEPTION_RESULT = "PERCEPTION_RESULT"
    WORLD_MODEL_UPDATE = "WORLD_MODEL_UPDATE"
    REASONING_SUMMARY = "REASONING_SUMMARY"
    ACTION_PROPOSAL = "ACTION_PROPOSAL"
    AUTHORITY_STATE = "AUTHORITY_STATE"
    FEED_STATUS = "FEED_STATUS"
    SYSTEM_FAULT = "SYSTEM_FAULT"


@dataclass(frozen=True)
class TimelineEvent:
    event_id: str
    robot_id: str
    sequence_number: int
    event_time_ms: int
    received_at_ms: int
    clock_domain: str
    event_type: TimelineEventType
    evidence_class: TimelineEvidenceClass
    source_id: str
    source_ref: str
    payload: dict[str, Any]
    schema_version: int = 1


@dataclass(frozen=True)
class TimelineEntry:
    kind: str
    event: dict[str, Any] | None
    message: str
