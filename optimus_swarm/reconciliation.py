from collections import Counter
from typing import Iterable

from optimus_swarm.recovery_models import (
    ActiveLeaseRecord,
    IssueSeverity,
    RecoveryIssue,
    RecoveryReport,
    RecoveryStatus,
    WorkerHeartbeat,
)


def reconcile_swarm(
    *,
    now_ms: int,
    known_worker_ids: set[str],
    known_task_ids: set[str],
    leases: Iterable[ActiveLeaseRecord],
    heartbeats: Iterable[WorkerHeartbeat],
    max_clock_skew_ms: int = 5_000,
    max_heartbeat_age_ms: int = 15_000,
    max_future_heartbeat_ms: int = 2_000,
) -> RecoveryReport:
    issues: list[RecoveryIssue] = []
    lease_list = list(leases)
    heartbeat_list = list(heartbeats)

    def issue(code, severity, detail):
        issues.append(RecoveryIssue(code, severity, detail))

    if now_ms < 0:
        issue("INVALID_CLOCK", IssueSeverity.CRITICAL, "Current timestamp is negative.")

    if min(max_clock_skew_ms, max_heartbeat_age_ms, max_future_heartbeat_ms) < 0:
        issue("INVALID_POLICY", IssueSeverity.CRITICAL, "Time tolerances must be non-negative.")

    heartbeat_counts = Counter(heartbeat.worker_id for heartbeat in heartbeat_list)
    for worker_id, count in heartbeat_counts.items():
        if count > 1:
            issue(
                "DUPLICATE_HEARTBEAT",
                IssueSeverity.ERROR,
                f"Worker {worker_id!r} has {count} heartbeat records.",
            )

    latest_heartbeat = {}
    for heartbeat in heartbeat_list:
        if heartbeat.worker_id not in known_worker_ids:
            issue(
                "UNKNOWN_HEARTBEAT_WORKER",
                IssueSeverity.ERROR,
                f"Heartbeat belongs to unknown worker {heartbeat.worker_id!r}.",
            )
            continue

        if heartbeat.sequence < 0:
            issue(
                "INVALID_HEARTBEAT_SEQUENCE",
                IssueSeverity.ERROR,
                f"Worker {heartbeat.worker_id!r} has a negative sequence.",
            )

        if heartbeat.observed_at_ms > now_ms + max_future_heartbeat_ms:
            issue(
                "FUTURE_HEARTBEAT",
                IssueSeverity.CRITICAL,
                f"Worker {heartbeat.worker_id!r} reports a future timestamp.",
            )

        previous = latest_heartbeat.get(heartbeat.worker_id)
        if previous is None or heartbeat.sequence > previous.sequence:
            latest_heartbeat[heartbeat.worker_id] = heartbeat

    for worker_id in sorted(known_worker_ids):
        heartbeat = latest_heartbeat.get(worker_id)
        if heartbeat is None:
            issue("MISSING_HEARTBEAT", IssueSeverity.ERROR, f"No heartbeat exists for worker {worker_id!r}.")
            continue

        age_ms = now_ms - heartbeat.observed_at_ms
        if age_ms > max_heartbeat_age_ms:
            issue("STALE_HEARTBEAT", IssueSeverity.ERROR, f"Worker {worker_id!r} heartbeat is stale.")

        if not heartbeat.healthy:
            issue("UNHEALTHY_WORKER", IssueSeverity.ERROR, f"Worker {worker_id!r} reports unhealthy status.")

    lease_ids = [lease.lease_id for lease in lease_list]
    task_ids = [lease.task_id for lease in lease_list]
    worker_ids = [lease.worker_id for lease in lease_list]

    for lease_id, count in Counter(lease_ids).items():
        if count > 1:
            issue("DUPLICATE_LEASE_ID", IssueSeverity.CRITICAL, f"Lease ID {lease_id!r} appears {count} times.")

    for task_id, count in Counter(task_ids).items():
        if count > 1:
            issue("MULTIPLE_TASK_OWNERS", IssueSeverity.CRITICAL, f"Task {task_id!r} has {count} lease records.")

    for worker_id, count in Counter(worker_ids).items():
        if count > 1:
            issue("MULTIPLE_WORKER_LEASES", IssueSeverity.ERROR, f"Worker {worker_id!r} has {count} lease records.")

    valid_lease_ids = []
    expired_lease_ids = []

    for lease in lease_list:
        if not lease.lease_id or not lease.task_id or not lease.worker_id:
            issue("MISSING_LEASE_IDENTITY", IssueSeverity.CRITICAL, "Lease is missing an identity field.")
            continue

        if lease.task_id not in known_task_ids:
            issue("UNKNOWN_TASK", IssueSeverity.CRITICAL, f"Lease references unknown task {lease.task_id!r}.")

        if lease.worker_id not in known_worker_ids:
            issue("UNKNOWN_LEASE_WORKER", IssueSeverity.CRITICAL, f"Lease references unknown worker {lease.worker_id!r}.")

        if lease.generation < 1:
            issue("INVALID_LEASE_GENERATION", IssueSeverity.CRITICAL, f"Lease {lease.lease_id!r} has invalid generation.")

        if lease.issued_at_ms < 0 or lease.expires_at_ms <= lease.issued_at_ms:
            issue("INVALID_LEASE_INTERVAL", IssueSeverity.CRITICAL, f"Lease {lease.lease_id!r} has an invalid time interval.")
            continue

        if lease.issued_at_ms > now_ms + max_clock_skew_ms:
            issue("FUTURE_LEASE_ISSUE", IssueSeverity.CRITICAL, f"Lease {lease.lease_id!r} was issued in the future.")
            continue

        if lease.expires_at_ms <= now_ms:
            expired_lease_ids.append(lease.lease_id)
        else:
            valid_lease_ids.append(lease.lease_id)

    critical = any(item.severity == IssueSeverity.CRITICAL for item in issues)
    errors = any(item.severity == IssueSeverity.ERROR for item in issues)

    if critical:
        status = RecoveryStatus.INDETERMINATE
    elif errors or expired_lease_ids:
        status = RecoveryStatus.INHIBITED
    else:
        status = RecoveryStatus.READY

    return RecoveryReport(
        status=status,
        checked_at_ms=now_ms,
        issues=tuple(issues),
        valid_lease_ids=tuple(sorted(valid_lease_ids)),
        expired_lease_ids=tuple(sorted(expired_lease_ids)),
        physical_execution_authorized=False,
    )
