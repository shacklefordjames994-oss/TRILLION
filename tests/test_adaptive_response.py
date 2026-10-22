from dataclasses import replace

from optimus_swarm.adaptive_response import (
    AdaptivePolicy,
    AuthorityState,
    EnvironmentState,
    ResponseGrade,
    adaptive_response,
    gate_adaptive_proposal,
)


def base_state(**changes):
    state = EnvironmentState(
        distance_m=3.0,
        closing_speed_mps=0.2,
        distance_sigma_m=0.05,
        source_quality=1.0,
        freshness_quality=1.0,
        integrity_quality=1.0,
        unknown_fraction=0.0,
        hazard_severity=0.0,
        captured_at_ms=9900,
        received_at_ms=9950,
    )
    return replace(state, **changes)


def test_far_low_risk_state():
    result = adaptive_response(base_state(), now_ms=10000, authority_state=AuthorityState.CLEAR)
    assert result.accepted
    assert result.risk_score is not None
    assert result.risk_score < 1.0
    assert result.response_grade == ResponseGrade.G0_MONITOR
    assert result.physical_execution_permitted is False


def test_uncertainty_reduces_adjusted_distance():
    result = adaptive_response(
        base_state(distance_m=2.0, distance_sigma_m=0.25),
        now_ms=10000,
        authority_state=AuthorityState.CLEAR,
    )
    assert result.adjusted_distance_m == 1.5


def test_stale_data_fails_closed():
    result = adaptive_response(
        base_state(captured_at_ms=1000),
        now_ms=10000,
        authority_state=AuthorityState.CLEAR,
    )
    assert not result.accepted
    assert result.response_grade == ResponseGrade.G4_DATA_INVALID
    assert result.risk_score is None


def test_latched_authority_overrides_risk_score():
    result = adaptive_response(
        base_state(distance_m=0.1),
        now_ms=10000,
        authority_state=AuthorityState.LATCHED,
    )
    assert result.response_grade == ResponseGrade.G3_CRITICAL_INHIBIT
    assert result.risk_score is None
    assert not result.physical_execution_permitted


def test_invalid_normalized_input_rejected():
    result = adaptive_response(
        base_state(unknown_fraction=1.5),
        now_ms=10000,
        authority_state=AuthorityState.CLEAR,
    )
    assert not result.accepted
    assert result.response_grade == ResponseGrade.G4_DATA_INVALID


def test_bad_weight_sum_rejected():
    result = adaptive_response(
        base_state(),
        now_ms=10000,
        authority_state=AuthorityState.CLEAR,
        policy=AdaptivePolicy(weight_distance=0.9),
    )
    assert not result.accepted
    assert result.response_grade == ResponseGrade.G4_DATA_INVALID


def test_physical_execution_never_enabled():
    result = adaptive_response(
        base_state(distance_m=0.2, closing_speed_mps=1.5),
        now_ms=10000,
        authority_state=AuthorityState.CLEAR,
    )
    assert result.physical_execution_permitted is False
    assert result.response_grade == ResponseGrade.G2_HUMAN_REVIEW


def test_grade_gate_blocks_review_and_never_resets():
    caution = gate_adaptive_proposal(
        adaptive_response(
            base_state(distance_m=1.2, closing_speed_mps=0.4),
            now_ms=10000,
            authority_state=AuthorityState.CLEAR,
        )
    )
    critical = gate_adaptive_proposal(
        adaptive_response(base_state(distance_m=0.1), now_ms=10000, authority_state=AuthorityState.LATCHED)
    )
    assert caution["physical_execution_permitted"] is False
    assert caution["automatic_reset"] is False
    assert critical["response_blocked"] is True
    assert critical["review_required"] is True
    assert critical["automatic_reset"] is False
    assert critical["simulation_visible"] is False
