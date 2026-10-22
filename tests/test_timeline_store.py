import sqlite3

import pytest

from optimus_swarm.timeline_models import TimelineEvidenceClass, TimelineEvent, TimelineEventType
from optimus_swarm.timeline_store import TimelineIntegrityError, TimelineRejected, TimelineStore


def make_event(seq, *, event_id=None, time_ms=None, received_ms=None):
    return TimelineEvent(
        event_id=event_id or f"event-{seq}",
        robot_id="robot-sim-01",
        sequence_number=seq,
        event_time_ms=time_ms if time_ms is not None else seq * 10,
        received_at_ms=received_ms if received_ms is not None else seq * 10,
        clock_domain="SIMULATION_CLOCK",
        event_type=TimelineEventType.PERCEPTION_RESULT,
        evidence_class=TimelineEvidenceClass.SIMULATED,
        source_id="synthetic-test-source",
        source_ref=f"synthetic-frame-{seq}",
        payload={"object_count": seq},
    )


def test_append_and_replay(tmp_path):
    store = TimelineStore(tmp_path / "timeline.db")
    store.append(make_event(1))
    store.append(make_event(2))
    entries = store.replay(robot_id="robot-sim-01")
    events = [entry for entry in entries if entry.kind == "EVENT"]

    assert len(events) == 2
    assert events[0].event["sequence_number"] == 1
    assert events[1].event["evidence_class"] == "SIMULATED"


def test_duplicate_event_rejected(tmp_path):
    store = TimelineStore(tmp_path / "timeline.db")
    store.append(make_event(1))
    with pytest.raises(TimelineRejected):
        store.append(make_event(1))


def test_sequence_gap_is_visible(tmp_path):
    store = TimelineStore(tmp_path / "timeline.db")
    store.append(make_event(1))
    store.append(make_event(3))
    entries = store.replay()
    gaps = [entry for entry in entries if entry.kind == "SEQUENCE_GAP"]

    assert len(gaps) == 1
    assert "2 through 2" in gaps[0].message


def test_clock_regression_is_visible(tmp_path):
    store = TimelineStore(tmp_path / "timeline.db")
    store.append(make_event(1, time_ms=100))
    store.append(make_event(2, time_ms=50))
    entries = store.replay()
    assert any(entry.kind == "CLOCK_REGRESSION" for entry in entries)


def test_digest_mismatch_is_rejected(tmp_path):
    path = tmp_path / "timeline.db"
    store = TimelineStore(path)
    store.append(make_event(1))
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE timeline_events SET payload_json = ? WHERE event_id = ?",
            ('{"object_count":999}', "event-1"),
        )
    with pytest.raises(TimelineIntegrityError):
        store.replay()


def test_infinite_payload_is_rejected(tmp_path):
    store = TimelineStore(tmp_path / "timeline.db")
    event = make_event(1)
    event = TimelineEvent(**{**event.__dict__, "payload": {"invalid": float("inf")}})
    with pytest.raises(TimelineRejected):
        store.append(event)
