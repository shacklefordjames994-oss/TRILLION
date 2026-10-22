from dataclasses import replace

from optimus_swarm.adaptive_response import AuthorityState, EnvironmentState, adaptive_response
from optimus_swarm.sensor_consistency import (
    ConsistencyPolicy,
    ConsistencyStatus,
    SensorObservation,
    downstream_admission,
    evaluate_consistency,
)


def obs(oid, source, x, captured=1000, received=1010):
    return SensorObservation(
        observation_id=oid,
        source_id=source,
        object_id="person-1",
        frame_id="world-v1",
        captured_at_ms=captured,
        received_at_ms=received,
        position_m=(x, 0.0, 0.0),
        uncertainty_sigma_m=0.05,
    )


def test_close_positions_are_consistent():
    result = evaluate_consistency([obs("a", "camera-a", 1.0), obs("b", "depth-b", 1.1)], now_ms=1020)
    assert result.status == ConsistencyStatus.CONSISTENT
    assert result.accepted_for_downstream
    assert not result.physical_execution_permitted
    assert downstream_admission(result)["adaptive_scoring_permitted"] is True


def test_conflicting_positions_block_downstream():
    result = evaluate_consistency([obs("a", "camera-a", 1.0), obs("b", "depth-b", 3.0)], now_ms=1020)
    admission = downstream_admission(result)
    assert result.status == ConsistencyStatus.CONFLICT
    assert not result.accepted_for_downstream
    assert admission["adaptive_scoring_permitted"] is False
    assert admission["risk_score"] is None
    assert admission["physical_execution_permitted"] is False


def test_conflict_is_not_scored_as_a_safe_scene():
    result = evaluate_consistency([obs("a", "camera-a", 1.0), obs("b", "depth-b", 3.0)], now_ms=1020)
    assert downstream_admission(result)["adaptive_scoring_permitted"] is False
    safe_looking = EnvironmentState(
        distance_m=5.0,
        closing_speed_mps=0.0,
        distance_sigma_m=0.01,
        source_quality=1.0,
        freshness_quality=1.0,
        integrity_quality=1.0,
        unknown_fraction=0.0,
        hazard_severity=0.0,
        captured_at_ms=1000,
        received_at_ms=1010,
    )
    scored = adaptive_response(safe_looking, now_ms=1020, authority_state=AuthorityState.CLEAR)
    assert scored.physical_execution_permitted is False
    assert downstream_admission(result)["risk_score"] is None


def test_stale_observation_is_rejected():
    result = evaluate_consistency([obs("a", "camera-a", 1.0, captured=100, received=110)], now_ms=2000)
    assert result.status == ConsistencyStatus.STALE
    assert not result.accepted_for_downstream


def test_duplicate_observation_ids_are_rejected():
    result = evaluate_consistency([obs("same", "camera-a", 1.0), obs("same", "depth-b", 1.1)], now_ms=1020)
    assert result.status == ConsistencyStatus.INVALID


def test_impossible_implied_speed_is_rejected():
    current = obs("current", "camera-a", 10.0, captured=1100, received=1110)
    previous = {("camera-a", "person-1", "world-v1"): (1000, (0.0, 0.0, 0.0))}
    result = evaluate_consistency(
        [current],
        now_ms=1120,
        policy=ConsistencyPolicy(max_implied_speed_mps=2.0),
        previous_positions=previous,
    )
    assert result.status == ConsistencyStatus.INVALID
    assert not result.accepted_for_downstream
    assert any("IMPLAUSIBLE_IMPLIED_SPEED" in reason for reason in result.reasons)


def test_single_sensor_is_not_cross_sensor_validation():
    result = evaluate_consistency([obs("a", "camera-a", 1.0)], now_ms=1020)
    assert result.status == ConsistencyStatus.INSUFFICIENT_EVIDENCE
    assert not result.accepted_for_downstream


def test_different_objects_are_not_treated_as_agreement():
    other = replace(obs("b", "depth-b", 1.0), object_id="crate-1")
    result = evaluate_consistency([obs("a", "camera-a", 1.0), other], now_ms=1020)
    assert result.status == ConsistencyStatus.INSUFFICIENT_EVIDENCE
    assert result.reasons == ("NO_COMPARABLE_CROSS_SENSOR_PAIRS",)
    assert not result.accepted_for_downstream
