from dataclasses import dataclass

from optimus_swarm.environmental_cues import CueEvaluation, CueType, ResponseKind
from optimus_swarm.timeline_models import TimelineEvidenceClass, TimelineEvent, TimelineEventType
from optimus_swarm.timeline_store import TimelineStore


@dataclass(frozen=True)
class ReviewDecision:
    code: str
    physical_execution_permitted: bool = False
    inhibit_cleared: bool = False


def decide_review(
    evaluation: CueEvaluation,
    *,
    authority_latched: bool,
    reviewer_id: str | None = None,
    acknowledged: bool = False,
) -> ReviewDecision:
    """A review record may reveal a simulation proposal. It never clears an inhibit."""
    blocked = (
        not evaluation.accepted
        or authority_latched
        or any(cue.response == ResponseKind.BLOCK_PROPOSAL for cue in evaluation.cues)
    )
    if blocked:
        return ReviewDecision("BLOCKED")

    needs_review = any(cue.response == ResponseKind.REQUEST_HUMAN_REVIEW for cue in evaluation.cues)
    if needs_review and not acknowledged:
        return ReviewDecision("AWAITING_REVIEW")
    if needs_review and not (isinstance(reviewer_id, str) and reviewer_id.strip()):
        return ReviewDecision("REVIEW_REJECTED")
    return ReviewDecision("SIMULATION_VISIBLE")


def record_cues(
    store: TimelineStore,
    evaluation: CueEvaluation,
    *,
    start_sequence: int,
    received_at_ms: int,
) -> tuple[str, ...]:
    """Append cues for replay. Recording does not execute a proposal."""
    if type(start_sequence) is not int or start_sequence < 1:
        raise ValueError("start_sequence must be an integer of 1 or more")
    if type(received_at_ms) is not int or received_at_ms < 0:
        raise ValueError("received_at_ms must be a non-negative integer")

    digests: list[str] = []
    for offset, cue in enumerate(evaluation.cues):
        if cue.cue_type == CueType.INHIBIT_ACTIVE:
            event_type = TimelineEventType.AUTHORITY_STATE
        elif cue.cue_type == CueType.FEED_STALE:
            event_type = TimelineEventType.FEED_STATUS
        else:
            event_type = TimelineEventType.REASONING_SUMMARY
        event = TimelineEvent(
            event_id=cue.cue_id,
            robot_id=cue.robot_id,
            sequence_number=start_sequence + offset,
            event_time_ms=cue.created_at_ms,
            received_at_ms=received_at_ms,
            clock_domain="SIMULATION_CLOCK",
            event_type=event_type,
            evidence_class=TimelineEvidenceClass(cue.evidence_class.value),
            source_id=cue.source_id,
            source_ref=cue.evidence_id,
            payload={
                "cue_type": cue.cue_type.value,
                "severity": cue.severity.value,
                "response": cue.response.value,
                "title": cue.title,
                "physical_execution_permitted": False,
            },
        )
        digests.append(store.append(event))
    return tuple(digests)
