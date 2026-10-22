import pytest

from optimus_swarm.cue_presenter import present_cues
from optimus_swarm.environmental_cues import (
    AuthorityState,
    CueType,
    EnvironmentalInterpretation,
    EnvironmentalPolicy,
    EvidenceClass,
    FeedState,
    evaluate_environment,
)


def make_interpretation(**overrides):
    data = dict(
        interpretation_id="interp-001",
        robot_id="robot-sim-01",
        captured_at_ms=9500,
        received_at_ms=9550,
        source_id="synthetic-sensor",
        evidence_id="evidence-001",
        evidence_class=EvidenceClass.SIMULATED,
        feed_state=FeedState.LIVE,
        kind="OBJECT_DETECTED",
        confidence=0.92,
        distance_m=2.0,
        path_intersects_unknown=False,
        conflicting_sources=(),
        model_version="test-model-1",
        details="Synthetic test input",
    )
    data.update(overrides)
    return EnvironmentalInterpretation(**data)


def test_detected_object_creates_display_cue():
    result = evaluate_environment(make_interpretation(), now_ms=10000, authority_state=AuthorityState.CLEAR)
    assert result.accepted
    assert any(cue.cue_type == CueType.OBJECT_DETECTED for cue in result.cues)
    assert result.physical_execution_permitted is False


def test_stale_feed_does_not_create_object_detection():
    result = evaluate_environment(
        make_interpretation(captured_at_ms=1000),
        now_ms=10000,
        authority_state=AuthorityState.CLEAR,
        policy=EnvironmentalPolicy(max_age_ms=1000),
    )
    assert any(cue.cue_type == CueType.FEED_STALE for cue in result.cues)
    assert not any(cue.cue_type == CueType.OBJECT_DETECTED for cue in result.cues)


def test_unknown_path_requests_review():
    result = evaluate_environment(
        make_interpretation(path_intersects_unknown=True),
        now_ms=10000,
        authority_state=AuthorityState.CLEAR,
    )
    assert any(cue.cue_type == CueType.PATH_UNCERTAIN for cue in result.cues)


def test_latched_authority_blocks_proposals():
    result = evaluate_environment(make_interpretation(), now_ms=10000, authority_state=AuthorityState.LATCHED)
    assert any(cue.cue_type == CueType.INHIBIT_ACTIVE for cue in result.cues)
    assert all(not cue.physical_execution_permitted for cue in result.cues)


def test_simulated_evidence_stays_simulated():
    result = evaluate_environment(
        make_interpretation(evidence_class=EvidenceClass.SIMULATED),
        now_ms=10000,
        authority_state=AuthorityState.CLEAR,
    )
    assert all(cue.evidence_class == EvidenceClass.SIMULATED for cue in result.cues)


def test_presenter_has_no_actuation_permission():
    result = evaluate_environment(
        make_interpretation(distance_m=0.2),
        now_ms=10000,
        authority_state=AuthorityState.LATCHED,
    )
    ui = present_cues(result)
    assert ui["mode"] == "SIMULATION_ONLY"
    assert ui["response_blocked"] is True
    assert ui["physical_execution_permitted"] is False
    assert ui["visual_cues"]
    assert ui["audio_cues"]


def test_conflicting_sources_are_shown():
    result = evaluate_environment(
        make_interpretation(conflicting_sources=("depth-a", "depth-b")),
        now_ms=10000,
        authority_state=AuthorityState.CLEAR,
    )
    cue = next(item for item in result.cues if item.cue_type == CueType.CONFLICTING_EVIDENCE)
    assert "depth-a" in cue.message and "depth-b" in cue.message


def test_future_timestamp_is_rejected():
    result = evaluate_environment(
        make_interpretation(captured_at_ms=20000),
        now_ms=10000,
        authority_state=AuthorityState.CLEAR,
    )
    assert result.accepted is False
    assert "capture_time_in_future" in result.issues
    assert result.cues[0].cue_type == CueType.DATA_INVALID


def test_non_finite_values_and_bad_enums_are_rejected():
    distance = make_interpretation(distance_m=float("inf"))
    confidence = make_interpretation(confidence=float("nan"))
    bad_enum = make_interpretation(evidence_class="SIMULATED")
    for item, issue in (
        (distance, "invalid_distance"),
        (confidence, "invalid_confidence"),
        (bad_enum, "invalid_evidence_class"),
    ):
        result = evaluate_environment(item, now_ms=10000, authority_state=AuthorityState.CLEAR)
        assert result.accepted is False
        assert issue in result.issues
        assert result.physical_execution_permitted is False


def test_invalid_policy_is_rejected():
    result = evaluate_environment(
        make_interpretation(),
        now_ms=10000,
        authority_state=AuthorityState.CLEAR,
        policy=EnvironmentalPolicy(proximity_critical_m=2.0, proximity_warning_m=1.0),
    )
    assert result.accepted is False
    assert "invalid_proximity_critical_threshold" in result.issues


def test_bad_authority_type_is_rejected():
    with pytest.raises(TypeError):
        EnvironmentalInterpretation(
            **{
                **make_interpretation().__dict__,
                "authority_state": "CLEAR",
            }
        )
    result = evaluate_environment(make_interpretation(), now_ms=10000, authority_state="CLEAR")
    assert result.accepted is False
    assert "invalid_authority_state" in result.issues
