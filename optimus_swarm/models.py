from dataclasses import dataclass, asdict
from typing import Literal
import hashlib
import json


@dataclass(frozen=True)
class Experience:
    experience_id: str
    origin_robot_id: str
    task_type: str
    environment_version: str
    model_version: str
    outcome: str
    source: Literal["SIMULATION", "SENSOR", "HUMAN_REVIEW"]
    validation_status: Literal["PENDING", "VALIDATED", "REJECTED", "QUARANTINED"]
    evidence_hash: str
    confidence: float
    human_reviewer_id: str | None = None
    human_approval_id: str | None = None

    def __post_init__(self) -> None:
        if self.source not in ("SIMULATION", "SENSOR", "HUMAN_REVIEW"):
            raise ValueError("source")
        if self.validation_status not in (
            "PENDING",
            "VALIDATED",
            "REJECTED",
            "QUARANTINED",
        ):
            raise ValueError("validation_status")
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise TypeError("confidence")
        if not self.experience_id or not self.origin_robot_id:
            raise ValueError("identity")

    def payload(self) -> dict:
        return asdict(self)

    def digest(self) -> str:
        raw = json.dumps(
            self.payload(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class RetrievalContext:
    receiving_robot_id: str
    task_type: str
    environment_version: str
    model_version: str
    min_confidence: float = 0.90


@dataclass(frozen=True)
class GuardDecision:
    """Policy result. The last field is physical execution, always refused here."""

    allowed: bool
    code: str
    reason: str
    physical_execution: bool = False

