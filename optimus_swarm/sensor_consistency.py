from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable


class ConsistencyStatus(str, Enum):
    CONSISTENT = "CONSISTENT"
    CONFLICT = "CONFLICT"
    STALE = "STALE"
    INVALID = "INVALID"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class SensorObservation:
    observation_id: str
    source_id: str
    object_id: str
    frame_id: str
    captured_at_ms: int
    received_at_ms: int
    position_m: tuple[float, float, float]
    uncertainty_sigma_m: float


@dataclass(frozen=True)
class ConsistencyPolicy:
    max_age_ms: int = 500
    future_skew_ms: int = 100
    max_implied_speed_mps: float = 8.0
    minimum_time_delta_ms: int = 10
    conflict_distance_m: float = 0.5


@dataclass(frozen=True)
class ConsistencyResult:
    status: ConsistencyStatus
    accepted_for_downstream: bool
    residuals_m: tuple[tuple[str, str, float], ...]
    reasons: tuple[str, ...]
    physical_execution_permitted: bool = False


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_policy(policy: ConsistencyPolicy) -> list[str]:
    issues: list[str] = []
    for name in ("max_age_ms", "future_skew_ms", "minimum_time_delta_ms"):
        value = getattr(policy, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            issues.append(f"INVALID_POLICY:{name}")
    for name in ("max_implied_speed_mps", "conflict_distance_m"):
        value = getattr(policy, name)
        if not _finite_number(value) or value <= 0:
            issues.append(f"INVALID_POLICY:{name}")
    if policy.minimum_time_delta_ms == 0:
        issues.append("INVALID_POLICY:minimum_time_delta_ms")
    return issues


def _validate_observation(observation: SensorObservation, *, now_ms: int, policy: ConsistencyPolicy) -> list[str]:
    issues: list[str] = []
    for name in ("observation_id", "source_id", "object_id", "frame_id"):
        value = getattr(observation, name)
        if not isinstance(value, str) or not value.strip():
            issues.append(f"INVALID_FIELD:{name}")
    for name in ("captured_at_ms", "received_at_ms"):
        value = getattr(observation, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            issues.append(f"INVALID_TIMESTAMP:{name}")
    if not isinstance(observation.position_m, tuple) or len(observation.position_m) != 3:
        issues.append("INVALID_POSITION_SHAPE")
    elif not all(_finite_number(value) for value in observation.position_m):
        issues.append("NONFINITE_POSITION")
    if not _finite_number(observation.uncertainty_sigma_m) or observation.uncertainty_sigma_m < 0:
        issues.append("INVALID_UNCERTAINTY")
    if issues:
        return issues
    if observation.captured_at_ms > now_ms + policy.future_skew_ms:
        issues.append("CAPTURE_TIME_IN_FUTURE")
    if observation.received_at_ms > now_ms + policy.future_skew_ms:
        issues.append("RECEIVE_TIME_IN_FUTURE")
    if observation.received_at_ms < observation.captured_at_ms:
        issues.append("RECEIVED_BEFORE_CAPTURE")
    if now_ms - observation.captured_at_ms > policy.max_age_ms:
        issues.append("OBSERVATION_STALE")
    return issues


def evaluate_consistency(
    observations: Iterable[SensorObservation],
    *,
    now_ms: int,
    policy: ConsistencyPolicy = ConsistencyPolicy(),
    previous_positions: dict[tuple[str, str, str], tuple[int, tuple[float, float, float]]] | None = None,
) -> ConsistencyResult:
    """Validate a batch. This does not average sensors or authorize motion."""
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms < 0:
        return ConsistencyResult(ConsistencyStatus.INVALID, False, (), ("INVALID_NOW_TIMESTAMP",))

    policy_issues = _validate_policy(policy)
    if policy_issues:
        return ConsistencyResult(ConsistencyStatus.INVALID, False, (), tuple(policy_issues))

    items = list(observations)
    if not items:
        return ConsistencyResult(ConsistencyStatus.INSUFFICIENT_EVIDENCE, False, (), ("NO_OBSERVATIONS",))

    issues: list[str] = []
    for item in items:
        issues.extend(f"{item.observation_id}:{issue}" for issue in _validate_observation(item, now_ms=now_ms, policy=policy))
    if issues:
        status = ConsistencyStatus.STALE if any("OBSERVATION_STALE" in issue for issue in issues) else ConsistencyStatus.INVALID
        return ConsistencyResult(status, False, (), tuple(sorted(issues)))

    ids = [item.observation_id for item in items]
    if len(ids) != len(set(ids)):
        return ConsistencyResult(ConsistencyStatus.INVALID, False, (), ("DUPLICATE_OBSERVATION_ID",))

    residuals: list[tuple[str, str, float]] = []
    conflicts: list[str] = []
    for index, left in enumerate(items):
        for right in items[index + 1 :]:
            if left.object_id != right.object_id or left.frame_id != right.frame_id or left.source_id == right.source_id:
                continue
            distance = math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left.position_m, right.position_m)))
            residuals.append((left.observation_id, right.observation_id, distance))
            if distance > policy.conflict_distance_m:
                conflicts.append(f"SENSOR_DISAGREEMENT:{left.observation_id}:{right.observation_id}")

    history = previous_positions or {}
    for observation in items:
        key = (observation.source_id, observation.object_id, observation.frame_id)
        prior = history.get(key)
        if prior is None:
            continue
        prior_time, prior_position = prior
        if (
            isinstance(prior_time, bool)
            or not isinstance(prior_time, int)
            or prior_time < 0
            or not isinstance(prior_position, tuple)
            or len(prior_position) != 3
            or not all(_finite_number(value) for value in prior_position)
        ):
            return ConsistencyResult(ConsistencyStatus.INVALID, False, tuple(residuals), ("INVALID_PREVIOUS_OBSERVATION",))
        delta_ms = observation.captured_at_ms - prior_time
        if delta_ms <= 0:
            issues.append(f"{observation.observation_id}:NONINCREASING_CAPTURE_TIME")
            continue
        if delta_ms < policy.minimum_time_delta_ms:
            issues.append(f"{observation.observation_id}:TIME_DELTA_TOO_SMALL")
            continue
        displacement = math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(observation.position_m, prior_position)))
        implied_speed = displacement / (delta_ms / 1000.0)
        if implied_speed > policy.max_implied_speed_mps:
            issues.append(f"{observation.observation_id}:IMPLAUSIBLE_IMPLIED_SPEED")

    if issues:
        return ConsistencyResult(ConsistencyStatus.INVALID, False, tuple(residuals), tuple(sorted(issues + conflicts)))
    if conflicts:
        return ConsistencyResult(ConsistencyStatus.CONFLICT, False, tuple(residuals), tuple(sorted(conflicts)))

    distinct_sources = {item.source_id for item in items}
    if len(distinct_sources) < 2:
        return ConsistencyResult(
            ConsistencyStatus.INSUFFICIENT_EVIDENCE,
            False,
            tuple(residuals),
            ("FEWER_THAN_TWO_DISTINCT_SOURCES",),
        )
    if not residuals:
        return ConsistencyResult(
            ConsistencyStatus.INSUFFICIENT_EVIDENCE,
            False,
            (),
            ("NO_COMPARABLE_CROSS_SENSOR_PAIRS",),
        )
    return ConsistencyResult(ConsistencyStatus.CONSISTENT, True, tuple(residuals), ("PAIRWISE_CHECKS_PASSED",))


def downstream_admission(result: ConsistencyResult) -> dict[str, object]:
    """A conflict, stale reading, or invalid batch is not converted into a risk score."""
    permitted = result.status == ConsistencyStatus.CONSISTENT and result.accepted_for_downstream
    return {
        "status": result.status.value,
        "adaptive_scoring_permitted": permitted,
        "risk_score": None,
        "physical_execution_permitted": False,
    }
