from optimus_swarm.command_crypto import payload_digest
from optimus_swarm.integration_adapter import SimulationAdapter
from optimus_swarm.integration_models import PipelineResult, PipelineStatus
from optimus_swarm.secure_command_gateway import SecureCommandGateway
from optimus_swarm.secure_command_models import SignedCommand

ALLOWED_OPERATIONS = frozenset({"simulate_navigation", "simulate_pick", "simulate_place", "observe_simulated"})


class OmegaSimulationPipeline:
    def __init__(self, *, gateway: SecureCommandGateway, adapter: SimulationAdapter):
        self.gateway = gateway
        self.adapter = adapter

    @staticmethod
    def _operation(command: SignedCommand) -> str | None:
        payload = getattr(command, "payload", None)
        if not isinstance(payload, dict):
            return None
        operation = payload.get("operation")
        if not isinstance(operation, str) or operation not in ALLOWED_OPERATIONS:
            return None
        return operation

    def _journal(self, command, result: PipelineResult, *, now_ms: int, decision_code: str = "") -> None:
        journal = getattr(self.adapter, "journal", None)
        if journal is None:
            return
        try:
            digest = payload_digest(command.payload) if isinstance(getattr(command, "payload", None), dict) else ""
        except Exception:
            digest = ""
        journal(
            command_id=result.command_id,
            status=result.status.value,
            stage=result.stage,
            reason=result.reason,
            now_ms=now_ms,
            payload_digest=digest,
            decision_code=decision_code,
            coordinator_epoch=getattr(command, "coordinator_epoch", None),
        )

    def process(self, command: SignedCommand, *, now_ms: int) -> PipelineResult:
        command_id = getattr(command, "command_id", "")

        # Schema is checked before the gateway so a bad operation cannot consume a replay reservation.
        # A schema pass does not authorize execution.
        if self._operation(command) is None:
            result = PipelineResult(
                command_id=command_id,
                status=PipelineStatus.REJECTED,
                stage="SCHEMA",
                reason="INVALID_OPERATION",
            )
            self._journal(command, result, now_ms=now_ms)
            return result

        decision = self.gateway.authorize_simulation(command, now_ms=now_ms)
        if not decision.simulation_permitted:
            status = (
                PipelineStatus.INDETERMINATE
                if decision.status.value == "INDETERMINATE"
                else PipelineStatus.REJECTED
            )
            result = PipelineResult(
                command_id=command_id,
                status=status,
                stage="SECURITY_GATEWAY",
                reason=decision.code,
            )
            self._journal(command, result, now_ms=now_ms, decision_code=decision.code)
            return result

        snapshot = getattr(self.gateway, "inhibit_snapshot", None)
        if snapshot is not None:
            try:
                latched, _revision = snapshot()
            except Exception:
                result = PipelineResult(
                    command_id=command_id,
                    status=PipelineStatus.INDETERMINATE,
                    stage="SIMULATION_ADAPTER",
                    reason="INHIBIT_RECHECK_FAILED",
                )
                self._journal(command, result, now_ms=now_ms, decision_code=decision.code)
                return result
            if latched:
                result = PipelineResult(
                    command_id=command_id,
                    status=PipelineStatus.REJECTED,
                    stage="SIMULATION_ADAPTER",
                    reason="INHIBIT_STATE_CHANGED_DURING_ADMISSION",
                )
                self._journal(command, result, now_ms=now_ms, decision_code=decision.code)
                return result

        try:
            event = self.adapter.record(
                decision=decision,
                operation=self._operation(command) or "",
                payload_digest=payload_digest(command.payload),
                now_ms=now_ms,
            )
            result = PipelineResult(
                command_id=command_id,
                status=PipelineStatus.ACCEPTED,
                stage="SIMULATION_ADAPTER",
                reason="SIMULATION_EVENT_RECORDED",
                simulation_event_recorded=bool(event),
                physical_execution_authorized=False,
            )
            self._journal(command, result, now_ms=now_ms, decision_code=decision.code)
            return result
        except Exception:
            # Replay reservation may already be consumed. Do not retry the same command ID.
            result = PipelineResult(
                command_id=command_id,
                status=PipelineStatus.INDETERMINATE,
                stage="SIMULATION_ADAPTER",
                reason="ADAPTER_FAILURE",
            )
            self._journal(command, result, now_ms=now_ms, decision_code=decision.code)
            return result
