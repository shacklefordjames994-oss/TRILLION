from dataclasses import dataclass
import time


@dataclass(frozen=True)
class SafetySnapshot:
    swarm_id: str
    revision: int
    issued_at: int
    expires_at: int
    latched: bool
    issuer_id: str


@dataclass(frozen=True)
class SafetyCheck:
    allowed: bool
    code: str
    reason: str


class SafetyStateMonitor:
    """
    In-memory monitor for simulation testing only.

    Authentication must be performed before update() is called.
    A production monitor needs persistent anti-rollback state and
    authenticated messages.
    """

    def __init__(self, expected_swarm_id: str):
        self._swarm_id = expected_swarm_id
        self._last_revision = -1
        self._snapshot = None

    def update(self, snapshot: SafetySnapshot, now: int | None = None):
        now = int(time.time()) if now is None else now

        if snapshot.swarm_id != self._swarm_id:
            return SafetyCheck(False, "WRONG_SWARM", "Swarm identity mismatch.")

        if snapshot.revision < 1 or not snapshot.issuer_id:
            return SafetyCheck(False, "INVALID_STATE", "Required fields are invalid.")

        if snapshot.expires_at <= snapshot.issued_at:
            return SafetyCheck(False, "INVALID_TIME_RANGE", "Expiry is invalid.")

        if snapshot.issued_at > now or snapshot.expires_at <= now:
            return SafetyCheck(False, "STALE_STATE", "Safety state is not current.")

        if snapshot.revision <= self._last_revision:
            return SafetyCheck(
                False,
                "REPLAY_OR_ROLLBACK",
                "Revision is not newer than the last accepted revision.",
            )

        self._snapshot = snapshot
        self._last_revision = snapshot.revision

        if snapshot.latched:
            return SafetyCheck(False, "SWARM_INHIBITED", "Inhibit is active.")

        return SafetyCheck(True, "STATE_ACCEPTED", "State accepted for simulation.")

    def can_progress(self, now: int | None = None) -> SafetyCheck:
        now = int(time.time()) if now is None else now

        if self._snapshot is None:
            return SafetyCheck(
                False, "NO_TRUSTED_STATE", "No safety state has been accepted."
            )

        if self._snapshot.expires_at <= now:
            return SafetyCheck(
                False, "STALE_STATE", "Last accepted safety state has expired."
            )

        if self._snapshot.latched:
            return SafetyCheck(False, "SWARM_INHIBITED", "Inhibit is active.")

        return SafetyCheck(
            True, "SIMULATION_ONLY", "Simulation progression may be evaluated."
        )

    def physical_execution_allowed(self) -> bool:
        return False
