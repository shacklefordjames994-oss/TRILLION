from dataclasses import dataclass
from threading import RLock
from typing import Callable


@dataclass(frozen=True)
class InhibitSnapshot:
    latched: bool
    revision: int
    reason: str
    changed_at_ms: int


class InhibitState:
    def __init__(self, authorization_verifier: Callable[[str, str], bool]):
        self._lock = RLock()
        self._verify = authorization_verifier
        self._snapshot = InhibitSnapshot(
            latched=True,
            revision=1,
            reason="STARTUP_INHIBIT",
            changed_at_ms=0,
        )

    def snapshot(self) -> InhibitSnapshot:
        with self._lock:
            return self._snapshot

    def engage(self, *, reason: str, now_ms: int) -> InhibitSnapshot:
        if not reason.strip() or now_ms < 0:
            raise ValueError("Invalid inhibit request")

        with self._lock:
            self._snapshot = InhibitSnapshot(
                latched=True,
                revision=self._snapshot.revision + 1,
                reason=reason,
                changed_at_ms=now_ms,
            )
            return self._snapshot

    def reset(self, *, actor_id: str, authorization_id: str, reason: str, now_ms: int) -> InhibitSnapshot:
        if not all(isinstance(value, str) and value.strip() for value in (actor_id, authorization_id, reason)):
            raise PermissionError("Human authorization is required")

        if now_ms < 0:
            raise ValueError("Invalid timestamp")

        if not self._verify(actor_id, authorization_id):
            raise PermissionError("Authorization verification failed")

        with self._lock:
            self._snapshot = InhibitSnapshot(
                latched=False,
                revision=self._snapshot.revision + 1,
                reason=reason,
                changed_at_ms=now_ms,
            )
            return self._snapshot

    def permits_physical_execution(self) -> bool:
        return False
