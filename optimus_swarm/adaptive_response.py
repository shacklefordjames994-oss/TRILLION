from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class AuthorityState(str, Enum):
    CLEAR = "CLEAR"
    LATCHED = "LATCHED"
    INDETERMINATE = "INDETERMINATE"


class ResponseGrade(str, Enum):
    G0_MONITOR = "G0_MONITOR"
    G1_CAUTION = "G1_CAUTION"
    G2_HUMAN_REVIEW = "G2_HUMAN_REVIEW"
    G3_CRITICAL_INHIBIT = "G3_CRITICAL_INHIBIT"
    G4_DATA_INVALID = "G4_DATA_INVALID"


@dataclass(frozen=True)
class EnvironmentState:
    distance_m: float
    closing_speed_mps: float
    distance_sigma_m: float
    source_quality: float
    freshness_quality: float
    integrity_quality: float
    unknown_fraction: float
    hazard_severity: float
    captured_at_ms: int
    received_at_ms: int


@dataclass(frozen=True)
class AdaptivePolicy:
    max_age_ms: int = 500
    future_skew_ms: int = 100
    uncertainty_multiplier: float = 2.0
    warning_distance_m: float = 2.0
    critical_distance_m: float = 0.4
    max_closing_speed_mps: float = 2.0
    weight_distance: float = 0.35
    weight_speed: float = 0.20
    weight_hazard: float = 0.20
    weight_unknown: float = 0.15
    weight_data_quality: float = 0.10
    threshold_caution: float = 0.25
    threshold_review: float = 0.50
    threshold_critical: float = 0.75


@dataclass(frozen=True)
class AdaptiveDecision:
    accepted: bool
    risk_score: float | None
    response_grade: ResponseGrade
    time_to_contact_s: float | None
    adjusted_distance_m: float | None
    reasons: tuple[str, ...]
    physical_execution_permitted: bool = False


def clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _valid_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_policy(policy: AdaptivePolicy) -> list[str]:
    issues: list[str] = []
    numeric_fields = (
        "uncertainty_multiplier",
        "warning_distance_m",
        "critical_distance_m",
        "max_closing_speed_mps",
        "weight_distance",
        "weight_speed",
        "weight_hazard",
        "weight_unknown",
        "weight_data_quality",
        "threshold_caution",
        "threshold_review",
        "threshold_critical",
    )
    for name in numeric_fields:
        if not _valid_number(getattr(policy, name)):
            issues.append(f"invalid_policy_{name}")
    if issues:
        return issues
    if policy.max_age_ms < 0 or policy.future_skew_ms < 0:
        issues.append("invalid_policy_time_limits")
    if policy.uncertainty_multiplier < 0:
        issues.append("negative_uncertainty_multiplier")
    if policy.warning_distance_m <= policy.critical_distance_m:
        issues.append("warning_distance_must_exceed_critical_distance")
    if policy.critical_distance_m < 0 or policy.max_closing_speed_mps <= 0:
        issues.append("invalid_distance_or_speed_limits")
    weights = (
        policy.weight_distance,
        policy.weight_speed,
        policy.weight_hazard,
        policy.weight_unknown,
        policy.weight_data_quality,
    )
    if any(weight < 0 for weight in weights):
        issues.append("negative_risk_weight")
    if not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
        issues.append("risk_weights_must_sum_to_one")
    thresholds = (policy.threshold_caution, policy.threshold_review, policy.threshold_critical)
    if not all(0 < threshold < 1 for threshold in thresholds):
        issues.append("thresholds_must_be_between_zero_and_one")
    if not thresholds[0] < thresholds[1] < thresholds[2]:
        issues.append("thresholds_must_be_strictly_increasing")
    return issues


def _invalid(reasons: tuple[str, ...]) -> AdaptiveDecision:
    return AdaptiveDecision(False, None, ResponseGrade.G4_DATA_INVALID, None, None, reasons, False)


def adaptive_response(
    state: EnvironmentState,
    *,
    now_ms: int,
    authority_state: AuthorityState,
    policy: AdaptivePolicy = AdaptivePolicy(),
) -> AdaptiveDecision:
    policy_issues = _validate_policy(policy)
    if policy_issues:
        return _invalid(tuple(policy_issues))
    if type(now_ms) is not int or now_ms < 0:
        return _invalid(("invalid_current_time",))

    numeric_values = (
        state.distance_m,
        state.closing_speed_mps,
        state.distance_sigma_m,
        state.source_quality,
        state.freshness_quality,
        state.integrity_quality,
        state.unknown_fraction,
        state.hazard_severity,
    )
    if not all(_valid_number(value) for value in numeric_values):
        return _invalid(("non_finite_or_invalid_environment_input",))
    if (
        type(state.captured_at_ms) is not int
        or type(state.received_at_ms) is not int
        or state.captured_at_ms < 0
        or state.received_at_ms < 0
    ):
        return _invalid(("invalid_timestamps",))

    reasons: list[str] = []
    if state.distance_m < 0 or state.distance_sigma_m < 0:
        reasons.append("negative_distance_or_uncertainty")
    bounded = (
        state.source_quality,
        state.freshness_quality,
        state.integrity_quality,
        state.unknown_fraction,
        state.hazard_severity,
    )
    if any(value < 0 or value > 1 for value in bounded):
        reasons.append("normalized_inputs_out_of_range")
    if reasons:
        return _invalid(tuple(reasons))
    if state.captured_at_ms > now_ms + policy.future_skew_ms:
        return _invalid(("capture_time_in_future",))
    if now_ms - state.captured_at_ms > policy.max_age_ms:
        return _invalid(("environment_data_stale",))
    if state.received_at_ms > now_ms + policy.future_skew_ms:
        return _invalid(("receive_time_in_future",))
    if state.received_at_ms < state.captured_at_ms:
        return _invalid(("receive_time_precedes_capture_time",))
    if authority_state != AuthorityState.CLEAR:
        return AdaptiveDecision(
            False,
            None,
            ResponseGrade.G3_CRITICAL_INHIBIT,
            None,
            None,
            (f"authority_state_{authority_state.value}",),
            False,
        )

    quality = state.source_quality * state.freshness_quality * state.integrity_quality
    adjusted_distance = max(0.0, state.distance_m - policy.uncertainty_multiplier * state.distance_sigma_m)
    closing_speed = max(0.0, state.closing_speed_mps)
    time_to_contact = adjusted_distance / closing_speed if closing_speed > 1e-9 else None
    distance_risk = clip((policy.warning_distance_m - adjusted_distance) / (policy.warning_distance_m - policy.critical_distance_m))
    speed_risk = clip(closing_speed / policy.max_closing_speed_mps)
    risk = clip(
        policy.weight_distance * distance_risk
        + policy.weight_speed * speed_risk
        + policy.weight_hazard * state.hazard_severity
        + policy.weight_unknown * state.unknown_fraction
        + policy.weight_data_quality * (1.0 - quality)
    )

    if state.unknown_fraction > 0:
        reasons.append("unknown_environment_regions_present")
    if quality < 0.5:
        reasons.append("low_data_quality")
    if adjusted_distance <= policy.critical_distance_m:
        reasons.append("critical_adjusted_distance")
    if time_to_contact is not None and time_to_contact < 1.0:
        reasons.append("short_estimated_time_to_contact")

    if risk >= policy.threshold_critical:
        grade = ResponseGrade.G3_CRITICAL_INHIBIT
        reasons.append("risk_exceeds_critical_threshold")
    elif risk >= policy.threshold_review:
        grade = ResponseGrade.G2_HUMAN_REVIEW
        reasons.append("risk_requires_human_review")
    elif risk >= policy.threshold_caution:
        grade = ResponseGrade.G1_CAUTION
        reasons.append("risk_requires_caution")
    else:
        grade = ResponseGrade.G0_MONITOR
        reasons.append("monitoring_grade_only")

    return AdaptiveDecision(True, risk, grade, time_to_contact, adjusted_distance, tuple(reasons), False)


def gate_adaptive_proposal(decision: AdaptiveDecision) -> dict:
    """Map a grade into the cue boundary. This does not reset an inhibit or move a robot."""
    grade = decision.response_grade
    blocked = grade in {
        ResponseGrade.G2_HUMAN_REVIEW,
        ResponseGrade.G3_CRITICAL_INHIBIT,
        ResponseGrade.G4_DATA_INVALID,
    }
    return {
        "grade": grade.value,
        "risk_score": decision.risk_score,
        "reasons": list(decision.reasons),
        "simulation_visible": decision.accepted and grade in {ResponseGrade.G0_MONITOR, ResponseGrade.G1_CAUTION},
        "review_required": grade in {ResponseGrade.G2_HUMAN_REVIEW, ResponseGrade.G3_CRITICAL_INHIBIT},
        "response_blocked": blocked or not decision.accepted,
        "automatic_reset": False,
        "physical_execution_permitted": False,
    }
