from dataclasses import dataclass
from enum import Enum


class ExecutionStatus(str, Enum):
    EXECUTED = "EXECUTED"
    ALREADY_EXECUTED = "ALREADY_EXECUTED"
    REJECTED = "REJECTED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class ExecutionReceipt:
    command_id: str
    status: ExecutionStatus
    reason: str
    operation: str = ""
    simulation_only: bool = True
    physical_execution_authorized: bool = False


@dataclass(frozen=True)
class CrashItem:
    command_id: str
    classification: str
    detail: str


@dataclass(frozen=True)
class CrashRecoveryReport:
    status: str
    items: tuple[CrashItem, ...]
    auto_resumed: bool = False
    physical_execution_authorized: bool = False
