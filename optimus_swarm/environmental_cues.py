from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

class EvidenceClass(str, Enum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    SIMULATED = "SIMULATED"
    UNKNOWN = "UNKNOWN"


class FeedState(str, Enum):
    LIVE = "LIVE"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    INVALID = "INVALID"


class AuthorityState(str, Enum):
    CLEAR = "CLEAR"
    LATCHED = "LATCHED"
    INDETERMINATE = "INDETERMINATE"


class CueType(str, Enum):
    OBJECT_DETECTED = "OBJECT_DETECTED"
    PATH_UNCERTAIN = "PATH_UNCERTAIN"
    PROXIMITY_WARNING = "PROXIMITY_WARNING"
    FEED_STALE = "FEED_STALE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    INHIBIT_ACTIVE = "INHIBIT_ACTIVE"
    SIMULATION_RESPONSE = "SIMULATION_RESPONSE"
    DATA_INVALID = "DATA_INVALID"


class CueSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ResponseKind(str, Enum):
    DISPLAY_ONLY = "DISPLAY_ONLY"
    ALERT_OPERATOR = "ALERT_OPERATOR"
    REQUEST_HUMAN_REVIEW = "REQUEST_HUMAN_REVIEW"
    BLOCK_PROPOSAL = "BLOCK_PROPOSAL"


@dataclass(frozen=True)
class EnvironmentalInterpretation:
    interpretation_id: str
    robot_id: str
    captured_at_ms: int
    received_at_ms: int
    source_id: str
    evidence_id: str
    evidence_class: EvidenceClass
    feed_state: FeedState
    kind: str
    confidence: float | None
    distance_m: float | None = None
    path_intersects_unknown: bool = False
    conflicting_sources: tuple[str, ...] = ()
    model_version: str = ""
    details: str = ""


@dataclass(frozen=True)
class EnvironmentalPolicy:
    max_age_ms: int = 1000
    max_future_skew_ms: int = 100
    minimum_detection_confidence: float = 0.70
    proximity_warning_m: float = 1.0
    proximity_critical_m: float = 0.4


@dataclass(frozen=True)
class EnvironmentalCue:
    cue_id: str
    robot_id: str
    cue_type: CueType
    severity: CueSeverity
    evidence_class: EvidenceClass
    evidence_id: str
    source_id: str
    created_at_ms: int
    title: str
    message: str
    response: ResponseKind
    physical_execution_permitted: bool = False


@dataclass(frozen=True)
class CueEvaluation:
    interpretation_id: str
    accepted: bool
    cues: tuple[EnvironmentalCue, ...]
    issues: tuple[str, ...]
    physical_execution_permitted: bool = False


def evaluate_environment(
    item: EnvironmentalInterpretation,
    *,
    now_ms: int,
    authority_state: AuthorityState,
    policy: EnvironmentalPolicy = EnvironmentalPolicy(),
) -> CueEvaluation:
    issues: list[str] = []
    cues: list[EnvironmentalCue] = []

    def emit(cue_type: CueType, severity: CueSeverity, title: str, message: str, response: ResponseKind) -> None:
        cues.append(
            EnvironmentalCue(
                cue_id=f"{item.interpretation_id}:{cue_type.value}:{len(cues)}",
                robot_id=item.robot_id or "UNKNOWN",
                cue_type=cue_type,
                severity=severity,
                evidence_class=item.evidence_class if isinstance(item.evidence_class, EvidenceClass) else EvidenceClass.UNKNOWN,
                evidence_id=item.evidence_id or "MISSING",
                source_id=item.source_id or "UNKNOWN",
                created_at_ms=now_ms if type(now_ms) is int and now_ms >= 0 else 0,
                title=title,
                message=message,
                response=response,
                physical_execution_permitted=False,
            )
        )

    required_text = {
        "interpretation_id": item.interpretation_id,
        "robot_id": item.robot_id,
        "source_id": item.source_id,
        "evidence_id": item.evidence_id,
        "kind": item.kind,
    }
    for name, value in required_text.items():
        if not isinstance(value, str) or not value.strip():
            issues.append(f"missing_or_invalid_{name}")

    for name, value in (
        ("now_ms", now_ms),
        ("captured_at_ms", item.captured_at_ms),
        ("received_at_ms", item.received_at_ms),
    ):
        if type(value) is not int or value < 0:
            issues.append(f"invalid_{name}")

    if not isinstance(item.evidence_class, EvidenceClass):
        issues.append("invalid_evidence_class")
    if not isinstance(item.feed_state, FeedState):
        issues.append("invalid_feed_state")
    if not isinstance(authority_state, AuthorityState):
        issues.append("invalid_authority_state")

    if type(policy.max_age_ms) is not int or policy.max_age_ms < 0:
        issues.append("invalid_max_age_ms")
    if type(policy.max_future_skew_ms) is not int or policy.max_future_skew_ms < 0:
        issues.append("invalid_max_future_skew_ms")
    if not 0.0 <= policy.minimum_detection_confidence <= 1.0:
        issues.append("invalid_confidence_threshold")
    if policy.proximity_warning_m <= 0:
        issues.append("invalid_proximity_warning_threshold")
    if not (0 < policy.proximity_critical_m < policy.proximity_warning_m):
        issues.append("invalid_proximity_critical_threshold")

    if item.confidence is not None and (
        not isinstance(item.confidence, (int, float))
        or isinstance(item.confidence, bool)
        or not 0.0 <= item.confidence <= 1.0
    ):
        issues.append("invalid_confidence")

    if item.distance_m is not None and (
        not isinstance(item.distance_m, (int, float))
        or isinstance(item.distance_m, bool)
        or item.distance_m < 0
        or item.distance_m != item.distance_m
        or item.distance_m in (float("inf"), float("-inf"))
    ):
        issues.append("invalid_distance")

    if issues:
        emit(
            CueType.DATA_INVALID,
            CueSeverity.CRITICAL,
            "Environmental data rejected",
            "The interpretation has invalid or missing fields. Do not use it to justify a robot response.",
            ResponseKind.BLOCK_PROPOSAL,
        )
        return CueEvaluation(item.interpretation_id, False, tuple(cues), tuple(issues), False)

    if item.captured_at_ms > now_ms + policy.max_future_skew_ms:
        emit(
            CueType.DATA_INVALID,
            CueSeverity.CRITICAL,
            "Source timestamp invalid",
            "The capture timestamp is too far in the future.",
            ResponseKind.BLOCK_PROPOSAL,
        )
        return CueEvaluation(item.interpretation_id, False, tuple(cues), ("capture_time_in_future",), False)

    age_ms = now_ms - item.captured_at_ms
    if item.feed_state != FeedState.LIVE or age_ms > policy.max_age_ms:
        emit(
            CueType.FEED_STALE,
            CueSeverity.WARNING,
            "Environmental feed unavailable or stale",
            f"Feed state={item.feed_state.value}; capture age={age_ms} ms. Treat the current scene as uncertain.",
            ResponseKind.ALERT_OPERATOR,
        )
    else:
        if item.path_intersects_unknown:
            emit(
                CueType.PATH_UNCERTAIN,
                CueSeverity.WARNING,
                "Path intersects an unknown region",
                "The interpreted route crosses an area without sufficient validated environmental information.",
                ResponseKind.REQUEST_HUMAN_REVIEW,
            )
        if item.conflicting_sources:
            emit(
                CueType.CONFLICTING_EVIDENCE,
                CueSeverity.WARNING,
                "Environmental sources disagree",
                "Conflicting sources: "
                + ", ".join(item.conflicting_sources)
                + ". Inspect the source records before relying on this state.",
                ResponseKind.REQUEST_HUMAN_REVIEW,
            )
        if item.distance_m is not None and item.distance_m <= policy.proximity_critical_m:
            emit(
                CueType.PROXIMITY_WARNING,
                CueSeverity.CRITICAL,
                "Critical proximity estimate",
                "A supplied distance estimate is inside the configured critical threshold. This is a software alert, not a certified collision detector.",
                ResponseKind.ALERT_OPERATOR,
            )
        elif item.distance_m is not None and item.distance_m <= policy.proximity_warning_m:
            emit(
                CueType.PROXIMITY_WARNING,
                CueSeverity.WARNING,
                "Proximity warning",
                "A supplied distance estimate is inside the configured warning threshold. Verify its source and calibration.",
                ResponseKind.ALERT_OPERATOR,
            )
        if item.kind == "OBJECT_DETECTED" and item.confidence is not None and item.confidence >= policy.minimum_detection_confidence:
            emit(
                CueType.OBJECT_DETECTED,
                CueSeverity.INFO,
                "Object hypothesis available",
                f"Model {item.model_version or 'UNKNOWN'} reported an object hypothesis with confidence {item.confidence:.3f}. Evidence class remains {item.evidence_class.value}.",
                ResponseKind.DISPLAY_ONLY,
            )

    if authority_state != AuthorityState.CLEAR:
        emit(
            CueType.INHIBIT_ACTIVE,
            CueSeverity.CRITICAL,
            "Robot response inhibited",
            f"Authority state is {authority_state.value}. Do not execute a proposed response. Only the authorized human control path may change the inhibit state.",
            ResponseKind.BLOCK_PROPOSAL,
        )

    return CueEvaluation(
        interpretation_id=item.interpretation_id,
        accepted=True,
        cues=tuple(cues),
        issues=(),
        physical_execution_permitted=False,
    )
