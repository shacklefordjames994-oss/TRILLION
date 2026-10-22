from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from optimus_swarm.signed_policy import (
    PolicyVerifier,
    sign_policy,
)
from optimus_swarm.safety_contract import (
    SafetySnapshot,
    SafetyStateMonitor,
)


def test_signed_policy_and_rollback(tmp_path):
    private = Ed25519PrivateKey.generate()
    public = private.public_key()

    verifier = PolicyVerifier(
        {"test-key": public},
        str(tmp_path / "versions.db"),
    )

    try:
        policy_v2 = sign_policy(
            private,
            "test-key",
            "swarm-policy",
            2,
            100,
            500,
            ("observe_synthetic_state",),
        )
        ok, code = verifier.verify_and_accept(policy_v2, now=200)
        assert ok and code == "POLICY_ACCEPTED"

        policy_v1 = sign_policy(
            private,
            "test-key",
            "swarm-policy",
            1,
            100,
            500,
            ("observe_synthetic_state",),
        )
        ok, code = verifier.verify_and_accept(policy_v1, now=200)
        assert not ok
        assert code == "POLICY_ROLLBACK_REJECTED"
    finally:
        verifier.close()


def test_expired_safety_state_blocks_progression():
    monitor = SafetyStateMonitor("swarm-alpha")
    snapshot = SafetySnapshot(
        swarm_id="swarm-alpha",
        revision=1,
        issued_at=100,
        expires_at=150,
        latched=False,
        issuer_id="safety-controller",
    )

    result = monitor.update(snapshot, now=120)
    assert result.allowed

    result = monitor.can_progress(now=151)
    assert not result.allowed
    assert result.code == "STALE_STATE"


def test_latched_snapshot_inhibits():
    monitor = SafetyStateMonitor("swarm-alpha")
    snapshot = SafetySnapshot(
        swarm_id="swarm-alpha",
        revision=1,
        issued_at=100,
        expires_at=200,
        latched=True,
        issuer_id="safety-controller",
    )

    result = monitor.update(snapshot, now=120)
    assert not result.allowed
    assert result.code == "SWARM_INHIBITED"


def test_physical_execution_always_denied():
    monitor = SafetyStateMonitor("swarm-alpha")
    assert monitor.physical_execution_allowed() is False
