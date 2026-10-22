from optimus_swarm.simulation_execution import ExecutionStatus, IdempotentSimulator, InhibitProvider
from optimus_swarm.simulation_journal import SimulationJournal


class SimulationExecutionController:
    def __init__(self, *, journal: SimulationJournal, simulator: IdempotentSimulator, inhibit: InhibitProvider):
        self.journal = journal
        self.simulator = simulator
        self.inhibit = inhibit

    def execute_recorded(self, *, command_id: str, event_digest: str, now_ms: int) -> ExecutionStatus:
        if not command_id or not event_digest or now_ms < 0:
            return ExecutionStatus.REJECTED

        try:
            initial = self.inhibit.snapshot()
            if initial.latched:
                return ExecutionStatus.REJECTED

            claim = self.journal.claim_execution(
                command_id=command_id,
                expected_event_digest=event_digest,
                inhibit_revision=initial.revision,
                now_ms=now_ms,
            )

            if claim == "NO_RECORDED_EVENT":
                return ExecutionStatus.REJECTED
            if claim == "ALREADY_EXECUTED":
                return ExecutionStatus.ALREADY_EXECUTED
            if claim != "CLAIMED":
                return ExecutionStatus.INDETERMINATE

            if self.journal.unreconciled_legacy(command_id):
                self.journal.mark_indeterminate(command_id)
                return ExecutionStatus.INDETERMINATE

            current = self.inhibit.snapshot()
            if current.latched or current.revision != initial.revision:
                self.journal.mark_indeterminate(command_id)
                return ExecutionStatus.REJECTED

            result = self.simulator.apply_once(command_id=command_id, event_digest=event_digest)

            if result.command_id != command_id or not result.outcome_digest:
                self.journal.mark_indeterminate(command_id)
                return ExecutionStatus.INDETERMINATE

            finalized = self.journal.finalize_execution(
                command_id=command_id,
                outcome_digest=result.outcome_digest,
                now_ms=now_ms,
            )

            if finalized == "SIMULATION_EXECUTED":
                return ExecutionStatus.SIMULATION_EXECUTED
            if finalized == "ALREADY_EXECUTED":
                return ExecutionStatus.ALREADY_EXECUTED
            return ExecutionStatus.INDETERMINATE
        except Exception:
            try:
                self.journal.mark_indeterminate(command_id)
            except Exception:
                pass
            return ExecutionStatus.INDETERMINATE
