from optimus_swarm.timeline_models import TimelineEntry


def render_timeline(entries: list[TimelineEntry]) -> str:
    lines = [
        "OPTIMUS BRAIN | HISTORICAL EVIDENCE REPLAY",
        "=" * 48,
        "MODE: REPLAY ONLY — NO COMMANDS OR ACTUATION",
        "",
    ]
    for entry in entries:
        if entry.kind != "EVENT":
            lines.append(f"[{entry.kind}] {entry.message}")
            continue
        event = entry.event or {}
        lines.extend(
            [
                (
                    f"[{event.get('received_at_ms', 'UNKNOWN')} ms] "
                    f"{event.get('robot_id', 'UNKNOWN')} "
                    f"#{event.get('sequence_number', '?')} "
                    f"{event.get('event_type', 'UNKNOWN')}"
                ),
                f"  Evidence: {event.get('evidence_class', 'UNKNOWN')} | Source: {event.get('source_id', 'UNKNOWN')}",
                f"  Reference: {event.get('source_ref', 'NONE')}",
                f"  Digest: {event.get('event_digest', 'MISSING')}",
                f"  Payload: {event.get('payload', {})}",
                "",
            ]
        )
    return "\n".join(lines)
