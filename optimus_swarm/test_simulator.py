import hashlib

from optimus_swarm.simulation_execution import SimulatorResult


class TestSimulator:
    __test__ = False
    def __init__(self):
        self._outcomes: dict[str, str] = {}
        self.dispatch_count: dict[str, int] = {}

    def apply_once(self, *, command_id: str, event_digest: str) -> SimulatorResult:
        if command_id in self._outcomes:
            return SimulatorResult(
                command_id=command_id,
                outcome_digest=self._outcomes[command_id],
                already_applied=True,
            )

        digest = hashlib.sha256(f"{command_id}:{event_digest}:SIMULATION".encode()).hexdigest()
        self._outcomes[command_id] = digest
        self.dispatch_count[command_id] = self.dispatch_count.get(command_id, 0) + 1
        return SimulatorResult(command_id=command_id, outcome_digest=digest, already_applied=False)
