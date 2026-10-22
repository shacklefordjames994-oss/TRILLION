import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from optimus_swarm.command_gateway import CommandGateway
from optimus_swarm.command_models import CommandEnvelope, EvidenceClass
from optimus_swarm.command_policy import payload_digest
from optimus_swarm.inhibit_state import InhibitState
from optimus_swarm.simulation_adapter import SimulationAdapter


def main():
    now_ms = 100_000
    payload = {"action": "navigate_simulated", "target": "zone-A"}
    inhibit = InhibitState(authorization_verifier=lambda actor, approval: False)
    gateway = CommandGateway(
        coordinator_id="coordinator-A",
        current_epoch=1,
        inhibit_state=inhibit,
        epoch_validator=lambda coordinator, epoch: coordinator == "coordinator-A" and epoch == 1,
        lease_validator=lambda *args: True,
        replay_reserver=lambda command_id: True,
    )
    command = CommandEnvelope(
        command_id="command-startup",
        coordinator_id="coordinator-A",
        coordinator_epoch=1,
        task_id="task-1",
        worker_id="robot-1",
        lease_id="lease-1",
        generation=1,
        issued_at_ms=now_ms - 100,
        expires_at_ms=now_ms + 5000,
        evidence_class=EvidenceClass.SIMULATED,
        payload=payload,
        payload_digest=payload_digest(payload),
        signature_verified=True,
    )
    decision = gateway.authorize_simulation(command, now_ms=now_ms)
    receipt = SimulationAdapter().process(decision)
    print(
        json.dumps(
            {
                "code": decision.code,
                "simulation_permitted": decision.simulation_permitted,
                "adapter_result": receipt.result,
                "physical_execution_authorized": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
