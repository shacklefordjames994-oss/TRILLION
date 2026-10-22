"""Simulation task transitions. Physical execution is out of scope."""

from .guard import MemoryDecision, OmegaGuard

ALLOWLISTED_PHASES = {"observe", "move", "grasp", "carry", "release", "verify"}


class TaskRuntime:
    def __init__(self, guard: OmegaGuard):
        self.guard = guard
        self.phase = "idle"

    def transition(self, phase: str) -> MemoryDecision:
        latch = self.guard.check_kill_switch()
        if not latch.allowed:
            return latch
        if phase not in ALLOWLISTED_PHASES:
            return MemoryDecision(
                False,
                "DENY_PHASE",
                "Phase is not allowlisted.",
            )
        self.phase = phase
        return MemoryDecision(
            True,
            "TRANSITION_OK",
            "Kill switch is clear. Simulation transition only.",
        )
