from dataclasses import dataclass

from optimus_swarm.brain_models import AuthorityState, BrainSnapshot, EvidenceClass, FeedStatus


@dataclass(frozen=True)
class SnapshotValidation:
    accepted: bool
    issues: tuple[str, ...]
    physical_execution_enabled: bool = False


def validate_snapshot(snapshot: BrainSnapshot, *, now_ms: int, max_age_ms: int = 2_000) -> SnapshotValidation:
    issues: list[str] = []

    if not snapshot.snapshot_id:
        issues.append("MISSING_SNAPSHOT_ID")

    if now_ms < 0 or snapshot.created_at_ms < 0:
        issues.append("INVALID_TIMESTAMP")
    elif snapshot.created_at_ms > now_ms:
        issues.append("SNAPSHOT_FROM_FUTURE")
    elif now_ms - snapshot.created_at_ms > max_age_ms:
        issues.append("SNAPSHOT_STALE")

    if snapshot.authority_revision < 0:
        issues.append("INVALID_AUTHORITY_REVISION")

    if snapshot.authority_state == AuthorityState.INDETERMINATE:
        issues.append("AUTHORITY_STATE_INDETERMINATE")

    if snapshot.authority_state == AuthorityState.LATCHED:
        issues.append("AUTHORITY_INHIBIT_LATCHED")

    if snapshot.physical_execution_enabled:
        issues.append("PHYSICAL_EXECUTION_FLAG_MUST_BE_FALSE")

    robot_ids = [robot.robot_id for robot in snapshot.robot_views]
    if len(robot_ids) != len(set(robot_ids)):
        issues.append("DUPLICATE_ROBOT_ID")

    task_ids = [task.task_id for task in snapshot.tasks]
    if len(task_ids) != len(set(task_ids)):
        issues.append("DUPLICATE_TASK_ID")

    evidence_ids = [item.evidence_id for item in snapshot.evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        issues.append("DUPLICATE_EVIDENCE_ID")

    evidence_by_id = {item.evidence_id: item for item in snapshot.evidence}

    for item in snapshot.evidence:
        if not item.evidence_id or not item.source_id or not item.digest:
            issues.append("INCOMPLETE_EVIDENCE_REFERENCE")
        if item.captured_at_ms < 0 or item.captured_at_ms > now_ms:
            issues.append("INVALID_EVIDENCE_TIMESTAMP")

    for robot in snapshot.robot_views:
        if not robot.robot_id:
            issues.append("MISSING_ROBOT_ID")
        if robot.updated_at_ms < 0 or robot.updated_at_ms > now_ms:
            issues.append(f"INVALID_ROBOT_TIMESTAMP:{robot.robot_id}")
        if robot.unknown_region_count < 0:
            issues.append(f"INVALID_UNKNOWN_REGION_COUNT:{robot.robot_id}")
        if robot.feed_status != FeedStatus.LIVE:
            issues.append(f"ROBOT_FEED_NOT_LIVE:{robot.robot_id}")
        if robot.pose_evidence_class == EvidenceClass.OBSERVED and robot.pose_m is None:
            issues.append(f"OBSERVED_POSE_MISSING:{robot.robot_id}")

        for obj in robot.objects:
            if not obj.object_id or not obj.label:
                issues.append(f"INVALID_OBJECT_IDENTITY:{robot.robot_id}")
            if obj.confidence is not None and not (0.0 <= obj.confidence <= 1.0):
                issues.append(f"INVALID_CONFIDENCE:{obj.object_id}")
            if obj.evidence_class == EvidenceClass.OBSERVED and not obj.evidence_ids:
                issues.append(f"OBSERVED_OBJECT_WITHOUT_EVIDENCE:{obj.object_id}")
            for evidence_id in obj.evidence_ids:
                if evidence_id not in evidence_by_id:
                    issues.append(f"UNRESOLVED_EVIDENCE:{evidence_id}")

    for task in snapshot.tasks:
        for evidence_id in task.evidence_ids:
            if evidence_id not in evidence_by_id:
                issues.append(f"UNRESOLVED_TASK_EVIDENCE:{evidence_id}")

    return SnapshotValidation(
        accepted=not issues,
        issues=tuple(sorted(set(issues))),
        physical_execution_enabled=False,
    )
