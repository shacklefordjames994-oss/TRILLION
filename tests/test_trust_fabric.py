from dataclasses import replace

from optimus_swarm.evidence_policy import EvidenceClaim, EvidenceClass, validate_evidence_claim
from optimus_swarm.shared_memory_store import SharedMemoryStore
from optimus_swarm.trust_fabric import SharedExperience, TrustPolicy, validate_shared_experience


def sample_experience():
    return SharedExperience(
        experience_id="exp-0001",
        source_robot_id="robot-001",
        source_type="SIMULATED_SCENE_GRAPH",
        simulator_version="sim-0.1",
        model_version="perception-stub-0.1",
        created_at_ms=1000,
        experience_type="OBJECT_LOCALIZATION",
        validation_status="VALIDATED",
        confidence=0.95,
        payload={"object_class": "box", "position_world_xyz": [0.1, 0.2, 2.0]},
    ).sealed()


def test_valid_experience_is_accepted():
    decision = validate_shared_experience(sample_experience(), now_ms=2000, trusted_source_ids={"robot-001"})

    assert decision.accepted
    assert decision.physical_execution_authorized is False


def test_untrusted_source_is_rejected():
    decision = validate_shared_experience(sample_experience(), now_ms=2000, trusted_source_ids={"robot-002"})

    assert not decision.accepted
    assert "UNTRUSTED_SOURCE_ID" in decision.reason_codes


def test_modified_payload_fails_digest_check():
    experience = sample_experience()
    changed = replace(experience, payload={"object_class": "unknown"})

    decision = validate_shared_experience(changed, now_ms=2000, trusted_source_ids={"robot-001"})

    assert not decision.accepted
    assert "DIGEST_MISMATCH" in decision.reason_codes


def test_stale_experience_is_rejected():
    decision = validate_shared_experience(
        sample_experience(),
        now_ms=100_000,
        trusted_source_ids={"robot-001"},
        policy=TrustPolicy(max_age_ms=1000),
    )

    assert not decision.accepted
    assert "STALE_EXPERIENCE" in decision.reason_codes


def test_memory_rejects_duplicate_id():
    store = SharedMemoryStore()
    item = sample_experience()

    first = store.publish(item, now_ms=2000, trusted_source_ids={"robot-001"})
    second = store.publish(item, now_ms=2000, trusted_source_ids={"robot-001"})

    assert first.accepted
    assert not second.accepted
    assert "DUPLICATE_EXPERIENCE_ID" in second.reason_codes
    store.close()


def test_memory_revalidates_on_retrieval():
    store = SharedMemoryStore()
    item = sample_experience()
    store.publish(item, now_ms=2000, trusted_source_ids={"robot-001"})

    fresh = store.retrieve(now_ms=3000, trusted_source_ids={"robot-001"})
    stale = store.retrieve(
        now_ms=100_000,
        trusted_source_ids={"robot-001"},
        policy=TrustPolicy(max_age_ms=1000),
    )

    assert len(fresh) == 1
    assert len(stale) == 0
    store.close()


def test_simulated_claim_is_not_promoted_to_observed():
    claim = EvidenceClaim(
        evidence_class=EvidenceClass.SIMULATED,
        source_id="robot-001",
        source_record_digest="a" * 64,
        explanation="Synthetic scene-graph localization",
    )

    result = validate_evidence_claim(claim, source_verified=True)

    assert result.accepted
    assert result.reason == "EVIDENCE_CLASS_PRESERVED"
    assert result.effective_class == EvidenceClass.SIMULATED
    assert result.effective_class != EvidenceClass.OBSERVED
