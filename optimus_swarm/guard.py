"""Receiver-side policy and the fleet kill switch.

The latch is software in this package. It is not a hardware e-stop,
and an accepted memory is never a motion command.
"""

from dataclasses import dataclass, asdict
from enum import Enum
from hashlib import sha256
import hmac
import json
import time
import uuid

from .models import Experience, RetrievalContext

AUTHORIZED_RESETTERS = {
    "operator-01": "omega-operator-token",
}


@dataclass(frozen=True)
class MemoryDecision:
    allowed: bool
    code: str
    reason: str


@dataclass(frozen=True)
class TaskProposal:
    task_id: str
    action: str
    target: str
    force_n: float
    speed_mps: float
    confidence: float
    human_approved: bool = False


@dataclass
class SafetyConfig:
    max_force_n: float = 10.0
    max_speed_mps: float = 0.25
    min_confidence: float = 0.90
    emergency_stop: bool = False
    simulation_only: bool = True


class Decision(str, Enum):
    ALLOW_SIMULATION = "ALLOW_SIMULATION"
    DENY = "DENY"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"


class OmegaGuard:
    """Research prototype. Not a certified robot safety controller."""

    ALLOWED_ACTIONS = {"observe", "move", "grasp", "release"}

    def __init__(self, config=None):
        self.config = config or SafetyConfig()
        self.events = []
        self.latched = False
        self.latch_requested_by: str | None = None
        self.latch_reason: str | None = None
        self.latch_reset_by: str | None = None

    def check_kill_switch(self) -> MemoryDecision:
        if self.latched:
            who = self.latch_requested_by or "unknown"
            why = self.latch_reason or "unspecified"
            return MemoryDecision(
                False,
                "KILL_SWITCH_LATCHED",
                f"Kill switch is latched by {who}: {why}",
            )
        return MemoryDecision(True, "CLEAR", "Kill switch is clear.")

    def request_inhibition(self, requester_id: str, reason: str) -> MemoryDecision:
        """Any robot may request inhibition. This does not authenticate them."""
        if not requester_id or not reason:
            return MemoryDecision(
                False,
                "INHIBIT_REJECTED",
                "Requester and reason are required.",
            )
        self.latched = True
        self.latch_requested_by = requester_id
        self.latch_reason = reason
        self.latch_reset_by = None
        self.config.emergency_stop = True
        return MemoryDecision(
            False,
            "LATCHED",
            f"Inhibition latched by {requester_id}: {reason}",
        )

    def authenticate(self, human_id: str, token: str) -> MemoryDecision:
        expected = AUTHORIZED_RESETTERS.get(human_id)
        if expected is None:
            return MemoryDecision(
                False,
                "RESET_DENIED",
                "Human is not on the reset allowlist.",
            )
        if not isinstance(token, str) or not hmac.compare_digest(expected, token):
            return MemoryDecision(
                False,
                "RESET_DENIED",
                "Authentication failed.",
            )
        return MemoryDecision(True, "AUTHENTICATED", "Prototype allowlist match.")

    def reset_latch(self, human_id: str, token: str) -> MemoryDecision:
        """Only an authenticated, authorized human may reset the latch."""
        auth = self.authenticate(human_id, token)
        if not auth.allowed:
            return auth
        if not self.latched:
            return MemoryDecision(True, "ALREADY_CLEAR", "Latch is already clear.")
        self.latched = False
        self.latch_reset_by = human_id
        self.config.emergency_stop = False
        self.latch_requested_by = None
        self.latch_reason = None
        return MemoryDecision(
            True,
            "LATCH_RESET",
            f"Authorized human {human_id} reset the latch.",
        )

    def validate_shared_memory(
        self,
        experience: Experience,
        context: RetrievalContext,
    ) -> MemoryDecision:
        latch = self.check_kill_switch()
        if not latch.allowed:
            return latch
        if experience.validation_status != "VALIDATED":
            return MemoryDecision(
                False,
                "NOT_VALIDATED",
                f"Validation status is {experience.validation_status}. "
                "Only VALIDATED records can be shared.",
            )
        if not 0 <= float(experience.confidence) <= 1:
            return MemoryDecision(
                False,
                "CONFIDENCE_RANGE",
                "Confidence must be between 0 and 1.",
            )
        if float(experience.confidence) < context.min_confidence:
            return MemoryDecision(
                False,
                "LOW_CONFIDENCE",
                "Confidence is below the receiver threshold.",
            )
        if experience.task_type != context.task_type:
            return MemoryDecision(
                False,
                "TASK_MISMATCH",
                "Task type does not match the receiver.",
            )
        if experience.environment_version != context.environment_version:
            return MemoryDecision(
                False,
                "ENVIRONMENT_MISMATCH",
                "Environment version does not match the receiver.",
            )
        if experience.model_version != context.model_version:
            return MemoryDecision(
                False,
                "MODEL_MISMATCH",
                "Model version does not match the receiver.",
            )
        evidence = experience.evidence_hash
        if len(evidence) != 64 or any(c not in "0123456789abcdef" for c in evidence):
            return MemoryDecision(
                False,
                "BAD_EVIDENCE",
                "Evidence hash is missing or not 64 hex characters.",
            )
        if experience.source == "HUMAN_REVIEW" and not experience.human_reviewer_id:
            return MemoryDecision(
                False,
                "MISSING_HUMAN_REVIEW",
                "Human review was claimed without a reviewer id.",
            )
        return MemoryDecision(
            True,
            "EVIDENCE_ONLY",
            "Accepted as evidence only. Not a motion command.",
        )

    def evaluate(self, proposal: TaskProposal) -> dict:
        reason = "Proposal passed software checks."
        decision = Decision.ALLOW_SIMULATION

        if self.config.emergency_stop or self.latched:
            decision, reason = Decision.DENY, "Emergency stop is active."
        elif not self.config.simulation_only:
            decision, reason = Decision.DENY, (
                "Physical execution is not supported by this prototype."
            )
        elif proposal.action not in self.ALLOWED_ACTIONS:
            decision, reason = Decision.DENY, "Action is not allowlisted."
        elif not proposal.task_id or not proposal.target:
            decision, reason = Decision.DENY, "Missing task ID or target."
        elif not all(
            map(
                lambda x: x >= 0,
                [proposal.force_n, proposal.speed_mps, proposal.confidence],
            )
        ):
            decision, reason = Decision.DENY, "Negative numeric value."
        elif proposal.confidence > 1:
            decision, reason = Decision.DENY, "Confidence must be at most 1."
        elif proposal.force_n > self.config.max_force_n:
            decision, reason = Decision.DENY, "Force limit exceeded."
        elif proposal.speed_mps > self.config.max_speed_mps:
            decision, reason = Decision.DENY, "Speed limit exceeded."
        elif proposal.confidence < self.config.min_confidence:
            decision, reason = Decision.REQUIRE_HUMAN, (
                "Confidence is below the configured threshold."
            )
        elif not proposal.human_approved:
            decision, reason = Decision.REQUIRE_HUMAN, (
                "Human approval is required for this prototype."
            )

        record = {
            "event_id": str(uuid.uuid4()),
            "timestamp_unix": time.time(),
            "proposal": asdict(proposal),
            "decision": decision.value,
            "reason": reason,
            "execution_enabled": False,
        }
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
        record["sha256"] = sha256(canonical.encode()).hexdigest()
        self.events.append(record)
        return record


OptimusOmegaGuard = OmegaGuard
