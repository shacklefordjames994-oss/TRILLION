from __future__ import annotations

from hashlib import sha256
import threading

from optimus_swarm.task_models import (
    CoordinationDecision,
    TaskLease,
    TaskSnapshot,
    TaskSpec,
    TaskStatus,
    WorkerStatus,
)


class TaskCoordinator:
    """
    In-memory, thread-safe simulation coordinator.

    This is not a distributed consensus system. A production deployment
    needs transactional shared storage or a consensus-backed authority.
    """

    def __init__(self, worker_ids: set[str]):
        if not worker_ids or any(not w.strip() for w in worker_ids):
            raise ValueError("worker_ids must contain valid IDs")

        self._lock = threading.RLock()
        self._workers = {worker_id: WorkerStatus.AVAILABLE for worker_id in worker_ids}
        self._tasks: dict[str, TaskSnapshot] = {}

    @staticmethod
    def _lease_id(task_id: str, generation: int) -> str:
        raw = f"{task_id}:{generation}".encode()
        return sha256(raw).hexdigest()[:24]

    def submit(self, task: TaskSpec) -> CoordinationDecision:
        if not task.task_id.strip() or not task.task_type.strip():
            return CoordinationDecision(False, "INVALID_TASK_IDENTITY")

        if not task.payload_digest.strip():
            return CoordinationDecision(False, "MISSING_PAYLOAD_DIGEST")

        with self._lock:
            if task.task_id in self._tasks:
                return CoordinationDecision(False, "DUPLICATE_TASK_ID")

            snapshot = TaskSnapshot(
                task=task,
                status=TaskStatus.PENDING,
                lease=None,
                generation=0,
                reason="TASK_SUBMITTED",
            )
            self._tasks[task.task_id] = snapshot
            return CoordinationDecision(True, "TASK_SUBMITTED", snapshot)

    def set_worker_status(self, worker_id: str, status: WorkerStatus) -> CoordinationDecision:
        with self._lock:
            if worker_id not in self._workers:
                return CoordinationDecision(False, "UNKNOWN_WORKER")

            self._workers[worker_id] = status
            return CoordinationDecision(True, "WORKER_STATUS_UPDATED")

    def _expire_if_needed(self, snapshot: TaskSnapshot, now_ms: int) -> TaskSnapshot:
        lease = snapshot.lease
        if snapshot.status == TaskStatus.LEASED and lease is not None and now_ms >= lease.expires_at_ms:
            self._workers[lease.worker_id] = WorkerStatus.AVAILABLE
            updated = TaskSnapshot(
                task=snapshot.task,
                status=TaskStatus.PENDING,
                lease=None,
                generation=snapshot.generation,
                reason="LEASE_EXPIRED",
            )
            self._tasks[snapshot.task.task_id] = updated
            return updated

        return snapshot

    def assign(
        self,
        task_id: str,
        worker_id: str,
        *,
        now_ms: int,
        lease_duration_ms: int,
    ) -> CoordinationDecision:
        if now_ms <= 0 or lease_duration_ms <= 0:
            return CoordinationDecision(False, "INVALID_TIME_ARGUMENTS")

        with self._lock:
            snapshot = self._tasks.get(task_id)
            if snapshot is None:
                return CoordinationDecision(False, "UNKNOWN_TASK")

            snapshot = self._expire_if_needed(snapshot, now_ms)

            if snapshot.status != TaskStatus.PENDING:
                return CoordinationDecision(False, "TASK_NOT_PENDING", snapshot)

            if worker_id not in self._workers:
                return CoordinationDecision(False, "UNKNOWN_WORKER")

            if self._workers[worker_id] != WorkerStatus.AVAILABLE:
                return CoordinationDecision(False, "WORKER_NOT_AVAILABLE")

            generation = snapshot.generation + 1
            lease = TaskLease(
                lease_id=self._lease_id(task_id, generation),
                task_id=task_id,
                worker_id=worker_id,
                issued_at_ms=now_ms,
                expires_at_ms=now_ms + lease_duration_ms,
                generation=generation,
            )
            updated = TaskSnapshot(
                task=snapshot.task,
                status=TaskStatus.LEASED,
                lease=lease,
                generation=generation,
                reason="LEASE_ISSUED",
            )
            self._tasks[task_id] = updated
            self._workers[worker_id] = WorkerStatus.BUSY
            return CoordinationDecision(True, "LEASE_ISSUED", updated)

    def heartbeat(
        self,
        task_id: str,
        worker_id: str,
        lease_id: str,
        *,
        now_ms: int,
    ) -> CoordinationDecision:
        with self._lock:
            snapshot = self._tasks.get(task_id)
            if snapshot is None:
                return CoordinationDecision(False, "UNKNOWN_TASK")

            snapshot = self._expire_if_needed(snapshot, now_ms)
            lease = snapshot.lease

            if snapshot.status != TaskStatus.LEASED or lease is None:
                return CoordinationDecision(False, "NO_ACTIVE_LEASE", snapshot)

            if lease.worker_id != worker_id or lease.lease_id != lease_id:
                return CoordinationDecision(False, "LEASE_IDENTITY_MISMATCH", snapshot)

            if now_ms >= lease.expires_at_ms:
                return CoordinationDecision(False, "LEASE_EXPIRED", snapshot)

            return CoordinationDecision(True, "HEARTBEAT_ACCEPTED", snapshot)

    def complete(
        self,
        task_id: str,
        worker_id: str,
        lease_id: str,
        *,
        now_ms: int,
    ) -> CoordinationDecision:
        with self._lock:
            snapshot = self._tasks.get(task_id)
            if snapshot is None:
                return CoordinationDecision(False, "UNKNOWN_TASK")

            snapshot = self._expire_if_needed(snapshot, now_ms)
            lease = snapshot.lease

            if snapshot.status != TaskStatus.LEASED or lease is None:
                return CoordinationDecision(False, "NO_ACTIVE_LEASE", snapshot)

            if lease.worker_id != worker_id or lease.lease_id != lease_id:
                return CoordinationDecision(False, "LEASE_IDENTITY_MISMATCH", snapshot)

            if now_ms >= lease.expires_at_ms:
                return CoordinationDecision(False, "LEASE_EXPIRED", snapshot)

            updated = TaskSnapshot(
                task=snapshot.task,
                status=TaskStatus.COMPLETED,
                lease=None,
                generation=snapshot.generation,
                reason="TASK_COMPLETED",
            )
            self._tasks[task_id] = updated
            self._workers[worker_id] = WorkerStatus.AVAILABLE
            return CoordinationDecision(True, "TASK_COMPLETED", updated)

    def cancel(self, task_id: str, *, authorized_human: bool, reason: str) -> CoordinationDecision:
        if not authorized_human:
            return CoordinationDecision(False, "HUMAN_AUTHORITY_REQUIRED")

        if not reason.strip():
            return CoordinationDecision(False, "CANCELLATION_REASON_REQUIRED")

        with self._lock:
            snapshot = self._tasks.get(task_id)
            if snapshot is None:
                return CoordinationDecision(False, "UNKNOWN_TASK")

            if snapshot.status in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
                return CoordinationDecision(False, "TASK_ALREADY_TERMINAL", snapshot)

            if snapshot.lease is not None:
                self._workers[snapshot.lease.worker_id] = WorkerStatus.AVAILABLE

            updated = TaskSnapshot(
                task=snapshot.task,
                status=TaskStatus.CANCELLED,
                lease=None,
                generation=snapshot.generation,
                reason=reason,
            )
            self._tasks[task_id] = updated
            return CoordinationDecision(True, "TASK_CANCELLED", updated)

    def get_snapshot(self, task_id: str) -> TaskSnapshot | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_snapshots(self) -> list[TaskSnapshot]:
        with self._lock:
            return [self._tasks[key] for key in sorted(self._tasks)]
