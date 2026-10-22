from collections.abc import Callable

from optimus_swarm.command_crypto import verify_signature
from optimus_swarm.durable_replay_store import DurableReplayStore
from optimus_swarm.key_registry import KeyRegistry
from optimus_swarm.secure_command_models import CommandDecision, DecisionStatus, SignedCommand


class SecureCommandGateway:
    def __init__(
        self,
        *,
        coordinator_id: str,
        key_registry: KeyRegistry,
        replay_store: DurableReplayStore,
        inhibit_snapshot: Callable[[], tuple[bool, int]],
        epoch_is_current: Callable[[str, int], bool],
        lease_is_current: Callable[..., bool],
        max_lifetime_ms: int = 30_000,
        max_clock_skew_ms: int = 2_000,
    ):
        self.coordinator_id = coordinator_id
        self.key_registry = key_registry
        self.replay_store = replay_store
        self.inhibit_snapshot = inhibit_snapshot
        self.epoch_is_current = epoch_is_current
        self.lease_is_current = lease_is_current
        self.max_lifetime_ms = max_lifetime_ms
        self.max_clock_skew_ms = max_clock_skew_ms

    @staticmethod
    def _deny(status, code, command_id=""):
        return CommandDecision(
            status=status,
            code=code,
            command_id=command_id,
            simulation_permitted=False,
            physical_execution_authorized=False,
        )

    def authorize_simulation(self, command: SignedCommand, *, now_ms: int) -> CommandDecision:
        command_id = getattr(command, "command_id", "")
        try:
            latched, initial_revision = self.inhibit_snapshot()
            if latched:
                return self._deny(DecisionStatus.REJECTED, "INHIBIT_LATCHED", command_id)

            if not isinstance(now_ms, int) or isinstance(now_ms, bool) or now_ms < 0:
                return self._deny(DecisionStatus.REJECTED, "INVALID_CURRENT_TIME", command_id)

            if command.schema_version != 1:
                return self._deny(DecisionStatus.REJECTED, "UNSUPPORTED_SCHEMA", command_id)

            if command.coordinator_id != self.coordinator_id:
                return self._deny(DecisionStatus.REJECTED, "COORDINATOR_MISMATCH", command_id)

            if command.evidence_class.value != "SIMULATED":
                return self._deny(DecisionStatus.REJECTED, "NON_SIMULATED_EVIDENCE_BLOCKED", command_id)

            if (
                command.issued_at_ms > now_ms + self.max_clock_skew_ms
                or command.expires_at_ms <= now_ms
                or command.expires_at_ms <= command.issued_at_ms
                or command.expires_at_ms - command.issued_at_ms > self.max_lifetime_ms
            ):
                return self._deny(DecisionStatus.REJECTED, "INVALID_COMMAND_TIME_WINDOW", command_id)

            if not all(
                (
                    command.command_id,
                    command.source_id,
                    command.key_id,
                    command.task_id,
                    command.worker_id,
                    command.lease_id,
                )
            ):
                return self._deny(DecisionStatus.REJECTED, "MISSING_COMMAND_IDENTITY", command_id)

            if command.coordinator_epoch < 0 or command.generation < 0:
                return self._deny(DecisionStatus.REJECTED, "INVALID_EPOCH_OR_GENERATION", command_id)

            key = self.key_registry.resolve(command.key_id, command.source_id)
            if key is None:
                return self._deny(DecisionStatus.REJECTED, "UNKNOWN_OR_REVOKED_KEY", command_id)

            verification = verify_signature(command, key.public_key_bytes)
            if not verification.valid:
                return self._deny(DecisionStatus.REJECTED, verification.code, command_id)

            if not self.epoch_is_current(command.coordinator_id, command.coordinator_epoch):
                return self._deny(DecisionStatus.REJECTED, "STALE_OR_UNKNOWN_EPOCH", command_id)

            if not self.lease_is_current(
                task_id=command.task_id,
                worker_id=command.worker_id,
                lease_id=command.lease_id,
                generation=command.generation,
                now_ms=now_ms,
            ):
                return self._deny(DecisionStatus.REJECTED, "LEASE_NOT_CURRENT", command_id)

            reserved = self.replay_store.reserve(
                command_id=command.command_id,
                source_id=command.source_id,
                key_id=command.key_id,
                coordinator_epoch=command.coordinator_epoch,
                payload_digest=command.payload_digest,
                now_ms=now_ms,
            )
            if not reserved:
                return self._deny(DecisionStatus.REJECTED, "DUPLICATE_COMMAND", command_id)

            latched_after, revision_after = self.inhibit_snapshot()
            if latched_after or revision_after != initial_revision:
                return self._deny(
                    DecisionStatus.REJECTED,
                    "INHIBIT_STATE_CHANGED_DURING_ADMISSION",
                    command_id,
                )

            return CommandDecision(
                status=DecisionStatus.ACCEPTED,
                code="SIMULATION_ADMISSION_ACCEPTED",
                command_id=command_id,
                simulation_permitted=True,
                physical_execution_authorized=False,
            )
        except Exception:
            return self._deny(DecisionStatus.INDETERMINATE, "SECURITY_DEPENDENCY_FAILURE", command_id)
