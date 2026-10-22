from dataclasses import dataclass
from threading import RLock

from optimus_swarm.physical_inhibit import PhysicalExecutionInhibit


class HumanAuthorityRequired(PermissionError):
    """Raised when an unauthorized actor attempts to reset the latch."""


class InvalidSafetyTransition(RuntimeError):
    """Raised when a safety-state transition is invalid."""


@dataclass(frozen=True)
class KillSwitchState:
    latched: bool
    revision: int
    reason: str
    changed_by: str
    authorization_id: str


@dataclass(frozen=True)
class KillSwitchEvent:
    revision: int
    action: str
    actor_id: str
    reason: str
    authorization_id: str


class HumanAuthorityKillSwitch:
    """
    In-process simulation policy latch.

    This class is not a certified emergency-stop controller.
    """

    def __init__(self, authorized_humans: set[str]):
        humans = frozenset(
            actor.strip()
            for actor in authorized_humans
            if isinstance(actor, str) and actor.strip()
        )
        if not humans:
            raise ValueError("At least one authorized human is required.")

        self._authorized_humans = humans
        self._lock = RLock()
        self._used_authorizations: set[str] = set()
        self._events: list[KillSwitchEvent] = []

        self._state = KillSwitchState(
            latched=True,
            revision=1,
            reason="Startup inhibit",
            changed_by="SYSTEM",
            authorization_id="BOOT",
        )
        self._events.append(
            KillSwitchEvent(
                revision=1,
                action="INHIBIT",
                actor_id="SYSTEM",
                reason="Startup inhibit",
                authorization_id="BOOT",
            )
        )

    @property
    def state(self) -> KillSwitchState:
        with self._lock:
            return self._state

    @property
    def audit_events(self) -> tuple[KillSwitchEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def engage(self, actor_id: str, reason: str) -> KillSwitchState:
        """Any identified actor may request inhibition."""
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("actor_id is required.")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason is required.")

        with self._lock:
            revision = self._state.revision + 1
            self._state = KillSwitchState(
                latched=True,
                revision=revision,
                reason=reason.strip(),
                changed_by=actor_id.strip(),
                authorization_id="INHIBIT",
            )
            self._events.append(
                KillSwitchEvent(
                    revision=revision,
                    action="INHIBIT",
                    actor_id=actor_id.strip(),
                    reason=reason.strip(),
                    authorization_id="INHIBIT",
                )
            )
            return self._state

    def reset(
        self,
        actor_id: str,
        authorization_id: str,
        reason: str,
    ) -> KillSwitchState:
        """Only an allowlisted human may clear the simulation latch."""
        if not isinstance(actor_id, str) or actor_id not in self._authorized_humans:
            raise HumanAuthorityRequired("Actor is not an authorized human.")
        if not isinstance(authorization_id, str) or not authorization_id.strip():
            raise HumanAuthorityRequired("A unique authorization ID is required.")
        if not isinstance(reason, str) or not reason.strip():
            raise HumanAuthorityRequired("A reset reason is required.")

        with self._lock:
            if not self._state.latched:
                raise InvalidSafetyTransition("Latch is already clear.")

            auth_id = authorization_id.strip()
            if auth_id in self._used_authorizations:
                raise HumanAuthorityRequired("Authorization ID has already been used.")

            self._used_authorizations.add(auth_id)
            revision = self._state.revision + 1
            self._state = KillSwitchState(
                latched=False,
                revision=revision,
                reason=reason.strip(),
                changed_by=actor_id,
                authorization_id=auth_id,
            )
            self._events.append(
                KillSwitchEvent(
                    revision=revision,
                    action="RESET",
                    actor_id=actor_id,
                    reason=reason.strip(),
                    authorization_id=auth_id,
                )
            )
            return self._state

    def permits_simulation(self) -> bool:
        with self._lock:
            return not self._state.latched

    def permits_physical_execution(self) -> bool:
        # The simulation latch and this inhibit are separate. Reset cannot release it.
        return PhysicalExecutionInhibit().permits()

    def is_authorized_human(self, actor_id: str) -> bool:
        """Read-only identity check. This does not clear the latch."""
        return isinstance(actor_id, str) and actor_id in self._authorized_humans
