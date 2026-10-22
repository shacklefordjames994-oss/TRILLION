import hashlib
import json

from optimus_swarm.command_gateway import CommandGateway
from optimus_swarm.command_models import CommandEnvelope, CommandStatus, EvidenceClass
from optimus_swarm.inhibit_state import InhibitState
from optimus_swarm.simulation_adapter import SimulationAdapter

NOW = 100_000


def digest(payload):
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def make_command(**overrides):
    payload = {"action": "navigate_simulated", "target": "zone-A"}
    fields = {
        "command_id": "command-1",
        "coordinator_id": "coordinator-A",
        "coordinator_epoch": 3,
        "task_id": "task-1",
        "worker_id": "robot-1",
        "lease_id": "lease-1",
        "generation": 2,
        "issued_at_ms": NOW - 100,
        "expires_at_ms": NOW + 5000,
        "evidence_class": EvidenceClass.SIMULATED,
        "payload": payload,
        "payload_digest": digest(payload),
        "signature_verified": True,
    }
    fields.update(overrides)
    return CommandEnvelope(**fields)


def make_gateway():
    inhibit = InhibitState(
        authorization_verifier=lambda actor, authorization: actor == "human-1" and authorization == "approval-1"
    )
    inhibit.reset(
        actor_id="human-1",
        authorization_id="approval-1",
        reason="Test simulation session",
        now_ms=NOW,
    )
    seen = set()
    gateway = CommandGateway(
        coordinator_id="coordinator-A",
        current_epoch=3,
        inhibit_state=inhibit,
        epoch_validator=lambda coordinator, epoch: coordinator == "coordinator-A" and epoch == 3,
        lease_validator=lambda *args: True,
        replay_reserver=lambda command_id: False if command_id in seen else not seen.add(command_id),
    )
    return gateway, inhibit


def test_valid_command_is_simulation_only():
    gateway, _ = make_gateway()
    decision = gateway.authorize_simulation(make_command(), now_ms=NOW)

    assert decision.status == CommandStatus.ACCEPTED
    assert decision.simulation_permitted
    assert not decision.physical_execution_authorized


def test_latched_inhibit_rejects_command():
    gateway, inhibit = make_gateway()
    inhibit.engage(reason="Test inhibit", now_ms=NOW)
    decision = gateway.authorize_simulation(make_command(), now_ms=NOW)

    assert decision.status == CommandStatus.REJECTED
    assert decision.code == "SYSTEM_INHIBITED"


def test_stale_epoch_rejected():
    gateway, _ = make_gateway()
    decision = gateway.authorize_simulation(make_command(coordinator_epoch=2), now_ms=NOW)

    assert decision.status == CommandStatus.REJECTED
    assert decision.code == "STALE_OR_UNKNOWN_EPOCH"


def test_expired_command_rejected():
    gateway, _ = make_gateway()
    decision = gateway.authorize_simulation(make_command(expires_at_ms=NOW), now_ms=NOW)

    assert decision.status == CommandStatus.REJECTED
    assert decision.code == "COMMAND_EXPIRED"


def test_tampered_payload_rejected():
    gateway, _ = make_gateway()
    decision = gateway.authorize_simulation(make_command(payload={"action": "tampered"}), now_ms=NOW)

    assert decision.status == CommandStatus.REJECTED
    assert decision.code == "PAYLOAD_DIGEST_MISMATCH"


def test_unverified_signature_rejected():
    gateway, _ = make_gateway()
    decision = gateway.authorize_simulation(make_command(signature_verified=False), now_ms=NOW)

    assert decision.status == CommandStatus.REJECTED
    assert decision.code == "SIGNATURE_NOT_VERIFIED"


def test_replayed_command_rejected():
    gateway, _ = make_gateway()
    command = make_command()
    first = gateway.authorize_simulation(command, now_ms=NOW)
    second = gateway.authorize_simulation(command, now_ms=NOW)

    assert first.status == CommandStatus.ACCEPTED
    assert second.status == CommandStatus.REJECTED
    assert second.code == "DUPLICATE_OR_REPLAYED_COMMAND"


def test_observed_evidence_rejected():
    gateway, _ = make_gateway()
    decision = gateway.authorize_simulation(make_command(evidence_class=EvidenceClass.OBSERVED), now_ms=NOW)

    assert decision.status == CommandStatus.REJECTED
    assert decision.code == "EVIDENCE_CLASS_NOT_ALLOWED"


def test_adapter_rejects_denied_decision():
    gateway, inhibit = make_gateway()
    inhibit.engage(reason="Emergency inhibit", now_ms=NOW)
    decision = gateway.authorize_simulation(make_command(), now_ms=NOW)
    receipt = SimulationAdapter().process(decision)

    assert not receipt.accepted
    assert not receipt.physical_execution_authorized


def test_adapter_never_authorizes_physical_execution():
    gateway, _ = make_gateway()
    decision = gateway.authorize_simulation(make_command(), now_ms=NOW)
    receipt = SimulationAdapter().process(decision)

    assert receipt.accepted
    assert receipt.result == "SIMULATION_EVENT_RECORDED"
    assert receipt.physical_execution_authorized is False
