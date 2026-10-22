from optimus_swarm.brain_models import BrainSnapshot


def project_snapshot(snapshot: BrainSnapshot) -> dict:
    """Create a display model without upgrading evidence status."""
    evidence = {
        item.evidence_id: {
            "class": item.evidence_class.value,
            "source_id": item.source_id,
            "captured_at_ms": item.captured_at_ms,
            "digest": item.digest,
            "model_version": item.model_version,
        }
        for item in snapshot.evidence
    }

    robots = []
    for robot in snapshot.robot_views:
        objects = []
        for obj in robot.objects:
            objects.append(
                {
                    "object_id": obj.object_id,
                    "label": obj.label,
                    "evidence_class": obj.evidence_class.value,
                    "confidence": obj.confidence,
                    "position_m": obj.position_m,
                    "evidence": [evidence[evidence_id] for evidence_id in obj.evidence_ids if evidence_id in evidence],
                    "display_warning": (
                        "UNVERIFIED_OR_INCOMPLETE"
                        if any(evidence_id not in evidence for evidence_id in obj.evidence_ids)
                        else None
                    ),
                }
            )
        robots.append(
            {
                "robot_id": robot.robot_id,
                "feed_status": robot.feed_status.value,
                "updated_at_ms": robot.updated_at_ms,
                "pose_evidence_class": robot.pose_evidence_class.value,
                "pose_m": robot.pose_m,
                "objects": objects,
                "unknown_region_count": robot.unknown_region_count,
            }
        )

    return {
        "snapshot_id": snapshot.snapshot_id,
        "created_at_ms": snapshot.created_at_ms,
        "authority_state": snapshot.authority_state.value,
        "authority_revision": snapshot.authority_revision,
        "robots": robots,
        "tasks": [
            {
                "task_id": task.task_id,
                "status": task.status,
                "proposed_action": task.proposed_action,
                "expected_outcome": task.expected_outcome,
                "evidence_ids": list(task.evidence_ids),
                "risk_flags": list(task.risk_flags),
            }
            for task in snapshot.tasks
        ],
        "physical_execution_enabled": False,
    }
