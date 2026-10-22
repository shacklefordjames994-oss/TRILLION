from dataclasses import dataclass
from enum import Enum


class PipelineStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class PipelineResult:
    command_id: str
    status: PipelineStatus
    stage: str
    reason: str
    simulation_event_recorded: bool = False
    physical_execution_authorized: bool = False
