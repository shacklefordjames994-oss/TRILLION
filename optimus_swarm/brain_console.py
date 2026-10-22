from __future__ import annotations

from typing import Any

EVIDENCE_CLASSES = {"OBSERVED", "INFERRED", "SIMULATED", "UNKNOWN"}


def _value(item: Any, field: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(field, default)
    return getattr(item, field, default)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _evidence_label(value: Any) -> str:
    label = _enum_value(value)
    if label not in EVIDENCE_CLASSES:
        return "UNKNOWN"
    return label


def _short(value: Any, limit: int = 160) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def render_console(snapshot: Any) -> str:
    """Render inspection data only; this function cannot issue commands."""
    lines: list[str] = []

    snapshot_id = _value(snapshot, "snapshot_id", "MISSING")
    timestamp = _value(snapshot, "created_at_ms", "UNKNOWN")
    authority = _enum_value(_value(snapshot, "authority_state", "INDETERMINATE"))
    revision = _value(snapshot, "authority_revision", "UNKNOWN")
    physical = _value(snapshot, "physical_execution_enabled", True)

    lines.extend(
        [
            "OPTIMUS BRAIN | HUMAN INSPECTION CONSOLE",
            "=" * 48,
            f"Snapshot: {snapshot_id}",
            f"Timestamp (ms): {timestamp}",
            f"Authority state: {authority}",
            f"Authority revision: {revision}",
            "Physical execution: DISABLED" if physical is False else "Physical execution: INVALID CONFIGURATION",
            "",
            "[1] ROBOT / SENSOR FEEDS",
        ]
    )

    for robot in _value(snapshot, "robot_views", ()) or ():
        robot_id = _value(robot, "robot_id", "UNKNOWN")
        feed = _enum_value(_value(robot, "feed_status", "INVALID"))
        pose_class = _evidence_label(_value(robot, "pose_evidence_class", "UNKNOWN"))
        pose = _value(robot, "pose_m", None)
        unknown_count = _value(robot, "unknown_region_count", "UNKNOWN")
        lines.append(f"- {robot_id}: feed={feed}; pose_class={pose_class}; pose={pose}; unknown_regions={unknown_count}")

        for obj in _value(robot, "objects", ()) or ():
            evidence_class = _evidence_label(_value(obj, "evidence_class", "UNKNOWN"))
            confidence = _value(obj, "confidence", None)
            position = _value(obj, "position_m", None)
            lines.append(
                f"    object={_short(_value(obj, 'label', 'UNKNOWN'), 60)}; "
                f"class={evidence_class}; confidence={confidence}; position={position}"
            )

    lines.extend(["", "[2] TASKS AND PROPOSED ACTIONS"])

    for task in _value(snapshot, "tasks", ()) or ():
        lines.append(
            f"- task={_value(task, 'task_id', 'UNKNOWN')}; "
            f"status={_value(task, 'status', 'UNKNOWN')}; "
            f"proposal={_short(_value(task, 'proposed_action', 'NONE'))}; "
            f"expected={_short(_value(task, 'expected_outcome', 'UNKNOWN'))}"
        )
        for flag in _value(task, "risk_flags", ()) or ():
            lines.append(f"    RISK: {_short(flag)}")

    lines.extend(["", "[3] EVIDENCE REGISTER"])

    for evidence in _value(snapshot, "evidence", ()) or ():
        lines.append(
            f"- id={_value(evidence, 'evidence_id', 'UNKNOWN')}; "
            f"class={_evidence_label(_value(evidence, 'evidence_class', 'UNKNOWN'))}; "
            f"source={_value(evidence, 'source_id', 'UNKNOWN')}; "
            f"time={_value(evidence, 'captured_at_ms', 'UNKNOWN')}; "
            f"model={_value(evidence, 'model_version', 'UNKNOWN')}; "
            f"digest={_short(_value(evidence, 'digest', 'MISSING'), 24)}"
        )

    lines.extend(
        [
            "",
            "[4] INTERPRETATION BOUNDARY",
            "- A displayed proposal is not an authorized command.",
            "- INFERRED and SIMULATED are not OBSERVED.",
            "- Missing, stale, or invalid data must remain visible.",
            "- This console has no physical actuation capability.",
        ]
    )

    return "\n".join(lines)
