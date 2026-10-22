import sqlite3

from optimus_swarm.durable_simulation_store import DurableSimulationStore
from optimus_swarm.execution_models import CrashItem, CrashRecoveryReport, ExecutionReceipt, ExecutionStatus
from optimus_swarm.integration_pipeline import ALLOWED_OPERATIONS


class SimulationExecutor:
    """
    Executes only a previously recorded simulation event.
    It has no actuator, motor, or hardware interface.
    """

    def __init__(self, store: DurableSimulationStore, *, inhibit_snapshot):
        self.store = store
        self.inhibit_snapshot = inhibit_snapshot

    def execute(self, command_id: str, *, now_ms: int) -> ExecutionReceipt:
        if not command_id or now_ms < 0:
            return ExecutionReceipt("", ExecutionStatus.REJECTED, "INVALID_EXECUTION_REQUEST")

        existing = self.store.get_execution(command_id)
        if existing is not None:
            return ExecutionReceipt(
                command_id,
                ExecutionStatus.ALREADY_EXECUTED,
                "IDEMPOTENT_EXECUTION",
                operation=existing,
            )

        event = self.store.get_event(command_id)
        if event is None:
            return ExecutionReceipt(command_id, ExecutionStatus.REJECTED, "EVENT_NOT_RECORDED")

        if event.operation not in ALLOWED_OPERATIONS or event.mode != "SIMULATION_ONLY":
            return ExecutionReceipt(command_id, ExecutionStatus.REJECTED, "OPERATION_NOT_SIMULATION", event.operation)

        try:
            latched, _revision = self.inhibit_snapshot()
        except Exception:
            return ExecutionReceipt(command_id, ExecutionStatus.INDETERMINATE, "INHIBIT_UNAVAILABLE", event.operation)

        if latched:
            return ExecutionReceipt(command_id, ExecutionStatus.REJECTED, "INHIBIT_LATCHED", event.operation)

        try:
            self.store.record_execution(command_id=command_id, operation=event.operation, now_ms=now_ms)
        except Exception:
            return ExecutionReceipt(command_id, ExecutionStatus.INDETERMINATE, "EXECUTION_STORE_FAILURE", event.operation)

        return ExecutionReceipt(
            command_id,
            ExecutionStatus.EXECUTED,
            "SIMULATION_EXECUTED",
            operation=event.operation,
        )


def recover_after_crash(store: DurableSimulationStore, replay_database_path: str) -> CrashRecoveryReport:
    """Classify incomplete work. Do not execute or resume anything."""
    try:
        events = {event.command_id: event for event in store.events()}
        executions = set(store.execution_ids())
        reserved = set(store.reserved_without_event(replay_database_path))
        reserved.update(_all_reserved(replay_database_path))
    except Exception:
        return CrashRecoveryReport("INDETERMINATE", (CrashItem("*", "RECOVERY_UNAVAILABLE", "State could not be read."),))

    items: list[CrashItem] = []
    for command_id in sorted(reserved | set(events) | executions):
        has_event = command_id in events
        has_execution = command_id in executions
        was_reserved = command_id in reserved
        if has_execution and not has_event:
            items.append(CrashItem(command_id, "INCONSISTENT_EXECUTION", "Execution exists without a simulation event."))
        elif was_reserved and not has_event:
            items.append(CrashItem(command_id, "RESERVED_WITHOUT_EVENT", "Replay reservation has no event. Do not retry."))
        elif has_event and not has_execution:
            items.append(CrashItem(command_id, "RECORDED_NOT_EXECUTED", "Event is recorded. Execution is not automatic."))
        elif has_event and has_execution:
            items.append(CrashItem(command_id, "SIMULATION_COMPLETE", "Recorded and executed in simulation only."))

    critical = any(item.classification == "INCONSISTENT_EXECUTION" for item in items)
    incomplete = any(item.classification in {"RESERVED_WITHOUT_EVENT", "RECORDED_NOT_EXECUTED"} for item in items)
    status = "INDETERMINATE" if critical else "HELD" if incomplete else "READY"
    return CrashRecoveryReport(status, tuple(items), auto_resumed=False, physical_execution_authorized=False)


def _all_reserved(replay_database_path: str) -> set[str]:
    connection = sqlite3.connect(replay_database_path, timeout=5.0)
    try:
        return {row[0] for row in connection.execute("SELECT command_id FROM accepted_commands").fetchall()}
    finally:
        connection.close()
