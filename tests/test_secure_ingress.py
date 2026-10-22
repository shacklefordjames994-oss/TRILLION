from dataclasses import replace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from optimus_swarm.envelope_verifier import verify_envelope
from optimus_swarm.replay_guard import ReplayGuard
from optimus_swarm.secure_ingress import receive_envelope
from optimus_swarm.signed_envelope import create_signed_envelope


def setup_case():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    trusted_keys = {
        "key-robot-001-v1": {
            "source_id": "robot-001",
            "public_key": public_key,
            "revoked": False,
        }
    }

    envelope = create_signed_envelope(
        private_key=private_key,
        message_id="message-001",
        source_id="robot-001",
        key_id="key-robot-001-v1",
        sequence_number=1,
        created_at_ms=1000,
        expires_at_ms=20_000,
        evidence_class="SIMULATED",
        payload={"object": "box", "x": 0.25, "z": 2.0},
    )

    return envelope, trusted_keys


def test_valid_signature_passes():
    envelope, trusted_keys = setup_case()
    result = verify_envelope(envelope, trusted_keys=trusted_keys, now_ms=2000)

    assert result.accepted
    assert result.physical_execution_authorized is False


def test_tampered_payload_fails():
    envelope, trusted_keys = setup_case()
    altered = replace(envelope, payload={"object": "box", "x": 99.0, "z": 2.0})

    result = verify_envelope(altered, trusted_keys=trusted_keys, now_ms=2000)

    assert not result.accepted


def test_expired_envelope_fails():
    envelope, trusted_keys = setup_case()
    result = verify_envelope(envelope, trusted_keys=trusted_keys, now_ms=21_000)

    assert not result.accepted
    assert "ENVELOPE_EXPIRED" in result.reason_codes


def test_revoked_key_fails():
    envelope, trusted_keys = setup_case()
    trusted_keys["key-robot-001-v1"]["revoked"] = True

    result = verify_envelope(envelope, trusted_keys=trusted_keys, now_ms=2000)

    assert not result.accepted
    assert "KEY_REVOKED_OR_NOT_ACTIVE" in result.reason_codes


def test_replayed_message_is_rejected():
    envelope, trusted_keys = setup_case()
    guard = ReplayGuard()

    first = receive_envelope(envelope, trusted_keys=trusted_keys, replay_guard=guard, now_ms=2000)
    second = receive_envelope(envelope, trusted_keys=trusted_keys, replay_guard=guard, now_ms=2000)

    assert first.accepted
    assert not second.accepted
    assert second.reason_codes == ("DUPLICATE_MESSAGE_ID",)
    guard.close()


def test_sequence_must_increase():
    guard = ReplayGuard()

    assert guard.reserve(source_id="robot-001", key_id="key-v1", message_id="m1", sequence_number=4)[0]

    accepted, reason = guard.reserve(
        source_id="robot-001",
        key_id="key-v1",
        message_id="m2",
        sequence_number=4,
    )

    assert not accepted
    assert reason == "REPLAYED_OR_OUT_OF_ORDER_SEQUENCE"
    guard.close()


def test_unknown_key_fails():
    envelope, _ = setup_case()
    result = verify_envelope(envelope, trusted_keys={}, now_ms=2000)

    assert not result.accepted
    assert "UNKNOWN_KEY_ID" in result.reason_codes


def test_acceptance_keeps_simulated_class_and_denies_motion():
    envelope, trusted_keys = setup_case()
    decision = receive_envelope(
        envelope,
        trusted_keys=trusted_keys,
        replay_guard=ReplayGuard(),
        now_ms=2000,
    )

    assert decision.accepted
    assert decision.evidence_class == "SIMULATED"
    assert envelope.evidence_class == "SIMULATED"
    assert decision.physical_execution_authorized is False


def test_closed_replay_store_rejects():
    guard = ReplayGuard()
    guard.close()
    accepted, reason = guard.reserve(
        source_id="robot-001",
        key_id="key-v1",
        message_id="m1",
        sequence_number=1,
    )

    assert not accepted
    assert reason == "REPLAY_STORE_ERROR"
