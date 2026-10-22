import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from optimus_swarm.safety_contract import SafetySnapshot, SafetyStateMonitor
from optimus_swarm.signed_policy import PolicyVerifier, SignedPolicy, sign_policy


def _verifier(tmp_path, public):
    return PolicyVerifier({"test-key": public}, str(tmp_path / "versions.db"))


def test_forged_policy_is_rejected(tmp_path):
    private = Ed25519PrivateKey.generate()
    verifier = _verifier(tmp_path, private.public_key())
    try:
        policy = sign_policy(
            private,
            "test-key",
            "swarm-policy",
            1,
            100,
            500,
            ("observe_synthetic_state",),
        )
        raw = bytearray(base64.b64decode(policy.signature_b64))
        raw[0] ^= 0x01
        forged = SignedPolicy(
            key_id=policy.key_id,
            policy_id=policy.policy_id,
            version=policy.version,
            issued_at=policy.issued_at,
            expires_at=policy.expires_at,
            mode=policy.mode,
            approved_actions=policy.approved_actions,
            signature_b64=base64.b64encode(bytes(raw)).decode("ascii"),
        )
        ok, code = verifier.verify_and_accept(forged, now=200)
        assert not ok
        assert code == "SIGNATURE_INVALID"
    finally:
        verifier.close()


def test_unknown_signing_key_is_rejected(tmp_path):
    private = Ed25519PrivateKey.generate()
    verifier = _verifier(tmp_path, private.public_key())
    try:
        policy = sign_policy(
            private,
            "unknown-key",
            "swarm-policy",
            1,
            100,
            500,
            ("observe_synthetic_state",),
        )
        ok, code = verifier.verify_and_accept(policy, now=200)
        assert not ok
        assert code == "UNTRUSTED_SIGNING_KEY"
    finally:
        verifier.close()


def test_expired_policy_is_rejected(tmp_path):
    private = Ed25519PrivateKey.generate()
    verifier = _verifier(tmp_path, private.public_key())
    try:
        policy = sign_policy(
            private,
            "test-key",
            "swarm-policy",
            1,
            100,
            150,
            ("observe_synthetic_state",),
        )
        ok, code = verifier.verify_and_accept(policy, now=160)
        assert not ok
        assert code == "POLICY_NOT_CURRENTLY_VALID"
    finally:
        verifier.close()


def test_missing_safety_state_blocks_progression():
    monitor = SafetyStateMonitor("swarm-alpha")
    result = monitor.can_progress(now=120)
    assert not result.allowed
    assert result.code == "NO_TRUSTED_STATE"


def test_revision_replay_is_rejected():
    monitor = SafetyStateMonitor("swarm-alpha")
    first = SafetySnapshot(
        "swarm-alpha", 2, 100, 400, False, "safety-controller"
    )
    second = SafetySnapshot(
        "swarm-alpha", 2, 110, 400, False, "safety-controller"
    )
    assert monitor.update(first, now=120).allowed
    replay = monitor.update(second, now=130)
    assert not replay.allowed
    assert replay.code == "REPLAY_OR_ROLLBACK"
