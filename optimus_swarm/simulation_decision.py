from dataclasses import dataclass

from optimus_swarm.cue_review import decide_review
from optimus_swarm.environmental_cues import CueEvaluation
from optimus_swarm.timeline_models import TimelineEvidenceClass, TimelineEvent, TimelineEventType
from optimus_swarm.timeline_store import TimelineStore


@dataclass(frozen=True)
class SimulationDecision:
    code: str
    actor_id: str
    authorization_id: str
    physical_execution_permitted: bool = False
    inhibit_cleared: bool = False


class SimulationDecisionLog:
    """Records an authorized human choice. It cannot reset the kill switch."""

    def __init__(self, kill_switch) -> None:
        self.kill_switch = kill_switch
        self._used: set[str] = set()

    def submit(
        self,
        evaluation: CueEvaluation,
        *,
        actor_id: str,
        authorization_id: str,
        choice: str,
    ) -> SimulationDecision:
        actor = actor_id.strip() if isinstance(actor_id, str) else ""
        if not self.kill_switch.is_authorized_human(actor):
            return SimulationDecision("UNAUTHORIZED", actor, "")

        if not isinstance(authorization_id, str) or not authorization_id.strip():
            return SimulationDecision("INVALID_AUTHORIZATION", actor, "")
        auth_id = authorization_id.strip()
        if auth_id in self._used:
            return SimulationDecision("REPLAYED_AUTHORIZATION", actor, auth_id)
        if choice not in {"APPROVE", "REJECT"}:
            return SimulationDecision("REJECTED", actor, auth_id)

        self._used.add(auth_id)
        latched = bool(self.kill_switch.state.latched)
        if choice == "REJECT":
            return SimulationDecision("SIMULATION_REJECTED", actor, auth_id)

        review = decide_review(
            evaluation,
            authority_latched=latched,
            reviewer_id=actor,
            acknowledged=True,
        )
        if latched or not self.kill_switch.permits_simulation() or review.code != "SIMULATION_VISIBLE":
            return SimulationDecision("BLOCKED", actor, auth_id)
        if self.kill_switch.permits_physical_execution():
            return SimulationDecision("BLOCKED", actor, auth_id)
        return SimulationDecision("SIMULATION_ADMITTED", actor, auth_id)


def record_simulation_decision(
    store: TimelineStore,
    decision: SimulationDecision,
    *,
    robot_id: str,
    sequence_number: int,
    now_ms: int,
) -> str:
    event = TimelineEvent(
        event_id=f"decision-{decision.authorization_id or 'none'}-{sequence_number}",
        robot_id=robot_id,
        sequence_number=sequence_number,
        event_time_ms=now_ms,
        received_at_ms=now_ms,
        clock_domain="SIMULATION_CLOCK",
        event_type=TimelineEventType.AUTHORITY_STATE,
        evidence_class=TimelineEvidenceClass.SIMULATED,
        source_id=decision.actor_id or "UNKNOWN",
        source_ref=decision.authorization_id or "NONE",
        payload={
            "code": decision.code,
            "physical_execution_permitted": False,
            "inhibit_cleared": False,
        },
    )
    return store.append(event)
