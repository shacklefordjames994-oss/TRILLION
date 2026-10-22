import dataclasses

import pytest

from optimus_swarm.command_crypto import generate_keypair, sign_command
from optimus_swarm.durable_replay_store import DurableReplayStore, ReplayStoreError
from optimus_swarm.key_registry import KeyRegistry, TrustedKey
from optimus_swarm.secure_command_gateway import SecureCommandGateway
from optimus_swarm.secure_command_models import DecisionStatus, EvidenceClass

NOW = 100_000


def signed(**overrides):
    private_bytes, public_bytes = generate_keypair()
    fields = {
        "private_key_bytes": private_bytes,
        "command_id": "command-1",
        "source_id": "operator-1",
        "key_id": "key-v1",
        "coordinator_id": "coordinator-A",
        "coordinator_epoch": 3,
        "task_id": "task-1",
        "worker_id": "robot-1",
        "lease_id": "lease-1",
        "generation": 2,
        "issued_at_ms": NOW - 100,
        "expires_at_ms": NOW + 5_000,
        "payload": {"action": "navigate_simulated", "target": "zone-A"},
    }
    fields.update(overrides)
    command = sign_command(**fields)
    return command, public_bytes


def gateway(tmp_path, public_bytes, *, revoked=False, inhibit=None, epoch_ok=True, lease_ok=True):
    registry = KeyRegistry(
        [TrustedKey("key-v1", "operator-1", public_bytes, revoked=revoked)]
    )
    store = DurableReplayStore(str(tmp_path / "replay.sqlite3"))
    state = {"latched": False, "revision": 1}
    if inhibit:
        state.update(inhibit)

    def snapshot():
        return state["latched"], state["revision"]

    return SecureCommandGateway(
        coordinator_id="coordinator-A",
        key_registry=registry,
        replay_store=store,
        inhibit_snapshot=snapshot,
        epoch_is_current=lambda coordinator, epoch: epoch_ok and coordinator == "coordinator-A" and epoch == 3,
        lease_is_current=lambda **kwargs: lease_ok,
    ), store, state


def test_valid_signature_admits_simulation_only(tmp_path):
    command, public_bytes = signed()
    gate, _, _ = gateway(tmp_path, public_bytes)
    decision = gate.authorize_simulation(command, now_ms=NOW)

    assert decision.status == DecisionStatus.ACCEPTED
    assert decision.code == "SIMULATION_ADMISSION_ACCEPTED"
    assert decision.simulation_permitted is True
    assert decision.physical_execution_authorized is False


def test_tampered_payload_is_rejected(tmp_path):
    command, public_bytes = signed()
    tampered = dataclasses.replace(command, payload={"action": "tampered"})
    gate, _, _ = gateway(tmp_path, public_bytes)
    decision = gate.authorize_simulation(tampered, now_ms=NOW)

    assert decision.status == DecisionStatus.REJECTED
    assert decision.code == "PAYLOAD_DIGEST_MISMATCH"
    assert decision.physical_execution_authorized is False


def test_altered_signed_field_is_rejected(tmp_path):
    command, public_bytes = signed()
    altered = dataclasses.replace(command, worker_id="robot-9")
    gate, _, _ = gateway(tmp_path, public_bytes)
    decision = gate.authorize_simulation(altered, now_ms=NOW)

    assert decision.code == "SIGNATURE_INVALID"


def test_revoked_key_is_rejected(tmp_path):
    command, public_bytes = signed()
    gate, _, _ = gateway(tmp_path, public_bytes, revoked=True)
    decision = gate.authorize_simulation(command, now_ms=NOW)

    assert decision.code == "UNKNOWN_OR_REVOKED_KEY"


def test_duplicate_command_is_rejected_across_store_restart(tmp_path):
    command, public_bytes = signed()
    gate, store, _ = gateway(tmp_path, public_bytes)
    first = gate.authorize_simulation(command, now_ms=NOW)
    restarted = DurableReplayStore(store.database_path)
    gate.replay_store = restarted
    second = gate.authorize_simulation(command, now_ms=NOW)

    assert first.code == "SIMULATION_ADMISSION_ACCEPTED"
    assert second.code == "DUPLICATE_COMMAND"


def test_latched_inhibit_rejects_before_admission(tmp_path):
    command, public_bytes = signed()
    gate, _, _ = gateway(tmp_path, public_bytes, inhibit={"latched": True})
    decision = gate.authorize_simulation(command, now_ms=NOW)

    assert decision.code == "INHIBIT_LATCHED"


def test_stale_epoch_and_bad_lease_are_rejected(tmp_path):
    command, public_bytes = signed()
    stale, _, _ = gateway(tmp_path, public_bytes, epoch_ok=False)
    assert stale.authorize_simulation(command, now_ms=NOW).code == "STALE_OR_UNKNOWN_EPOCH"

    bad_lease, _, _ = gateway(tmp_path, public_bytes, lease_ok=False)
    assert bad_lease.authorize_simulation(command, now_ms=NOW).code == "LEASE_NOT_CURRENT"


def test_non_simulated_evidence_is_blocked(tmp_path):
    command, public_bytes = signed()
    observed = dataclasses.replace(command, evidence_class=EvidenceClass.OBSERVED)
    gate, _, _ = gateway(tmp_path, public_bytes)
    decision = gate.authorize_simulation(observed, now_ms=NOW)

    assert decision.code == "NON_SIMULATED_EVIDENCE_BLOCKED"


def test_inhibit_change_during_admission_rejects_and_consumes_replay(tmp_path):
    command, public_bytes = signed()
    gate, store, state = gateway(tmp_path, public_bytes)
    calls = {"n": 0}

    def snapshot():
        calls["n"] += 1
        if calls["n"] > 1:
            state["revision"] = 2
        return state["latched"], state["revision"]

    gate.inhibit_snapshot = snapshot
    decision = gate.authorize_simulation(command, now_ms=NOW)
    assert decision.code == "INHIBIT_STATE_CHANGED_DURING_ADMISSION"
    assert store.reserve(
        command_id=command.command_id,
        source_id=command.source_id,
        key_id=command.key_id,
        coordinator_epoch=command.coordinator_epoch,
        payload_digest=command.payload_digest,
        now_ms=NOW,
    ) is False


def test_replay_store_failure_is_indeterminate(tmp_path):
    command, public_bytes = signed()
    gate, _, _ = gateway(tmp_path, public_bytes)

    class BrokenStore:
        def reserve(self, **kwargs):
            raise ReplayStoreError("REPLAY_STORE_UNAVAILABLE")

    gate.replay_store = BrokenStore()
    decision = gate.authorize_simulation(command, now_ms=NOW)

    assert decision.status == DecisionStatus.INDETERMINATE
    assert decision.code == "SECURITY_DEPENDENCY_FAILURE"
    assert decision.physical_execution_authorized is False


def test_registry_rejects_bad_keys():
    with pytest.raises(ValueError, match="INVALID_ED25519_PUBLIC_KEY_LENGTH"):
        KeyRegistry([TrustedKey("key-v1", "operator-1", b"short")])
    with pytest.raises(ValueError, match="DUPLICATE_KEY_ID"):
        KeyRegistry(
            [
                TrustedKey("key-v1", "operator-1", b"\x00" * 32),
                TrustedKey("key-v1", "operator-2", b"\x01" * 32),
            ]
        )
