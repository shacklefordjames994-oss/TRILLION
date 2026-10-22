import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from optimus_swarm.command_crypto import generate_keypair, sign_command
from optimus_swarm.durable_replay_store import DurableReplayStore
from optimus_swarm.key_registry import KeyRegistry, TrustedKey
from optimus_swarm.secure_command_gateway import SecureCommandGateway


def main():
    now_ms = 100_000
    private_bytes, public_bytes = generate_keypair()
    command = sign_command(
        private_key_bytes=private_bytes,
        command_id="command-startup",
        source_id="operator-1",
        key_id="key-v1",
        coordinator_id="coordinator-A",
        coordinator_epoch=1,
        task_id="task-1",
        worker_id="robot-1",
        lease_id="lease-1",
        generation=1,
        issued_at_ms=now_ms - 100,
        expires_at_ms=now_ms + 5_000,
        payload={"action": "navigate_simulated", "target": "zone-A"},
    )
    gateway = SecureCommandGateway(
        coordinator_id="coordinator-A",
        key_registry=KeyRegistry([TrustedKey("key-v1", "operator-1", public_bytes)]),
        replay_store=DurableReplayStore("/tmp/secure-command-replay.sqlite3"),
        inhibit_snapshot=lambda: (True, 1),
        epoch_is_current=lambda coordinator, epoch: True,
        lease_is_current=lambda **kwargs: True,
    )
    decision = gateway.authorize_simulation(command, now_ms=now_ms)
    print(
        json.dumps(
            {
                "code": decision.code,
                "simulation_permitted": decision.simulation_permitted,
                "physical_execution_authorized": decision.physical_execution_authorized,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
