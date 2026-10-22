from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ExecutionStatus(str, Enum):
    SIMULATION_EXECUTED = "SIMULATION_EXECUTED"
    ALREADY_EXECUTED = "ALREADY_EXECUTED"
    REJECTED = "REJECTED"
    RESERVED_WITHOUT_EVENT = "RESERVED_WITHOUT_EVENT"
    RECORDED_NOT_EXECUTED = "RECORDED_NOT_EXECUTED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class InhibitSnapshot:
    latched: bool
    revision: int


@dataclass(frozen=True)
class SimulatorResult:
    command_id: str
    outcome_digest: str
    already_applied: bool


class IdempotentSimulator(Protocol):
    def apply_once(self, *, command_id: str, event_digest: str) -> SimulatorResult:
        """Apply a simulation event at most once per command ID."""
        ...


class InhibitProvider(Protocol):
    def snapshot(self) -> InhibitSnapshot:
        ...
