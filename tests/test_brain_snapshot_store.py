import json
import sqlite3
from dataclasses import dataclass
from enum import Enum

import pytest

from optimus_swarm.brain_console import render_console
from optimus_swarm.brain_models import (
    AuthorityState,
    BrainSnapshot,
    EvidenceClass,
    FeedStatus,
    RobotView,
)
from optimus_swarm.brain_snapshot_store import BrainSnapshotStore, SnapshotIntegrityError, SnapshotRejected
from optimus_swarm.brain_validation import validate_snapshot


class Authority(str, Enum):
    LATCHED = "LATCHED"
    CLEAR = "CLEAR"


@dataclass(frozen=True)
class Validation:
    accepted: bool
    issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    created_at_ms: int
    authority_revision: int
    authority_state: Authority
    physical_execution_enabled: bool = False
    robot_views: tuple = ()
    tasks: tuple = ()
    evidence: tuple = ()


def accept_for_test(snapshot, now_ms):
    return Validation(accepted=True)


def test_persist_and_read_snapshot(tmp_path):
    path = tmp_path / "brain.db"
    store = BrainSnapshotStore(path, accept_for_test)
    snapshot = Snapshot(
        snapshot_id="snap-001",
        created_at_ms=1000,
        authority_revision=3,
        authority_state=Authority.LATCHED,
    )

    digest = store.publish(snapshot, now_ms=1100)
    recovered = store.get("snap-001")

    assert recovered is not None
    assert recovered["snapshot_id"] == "snap-001"
    assert recovered["authority_state"] == "LATCHED"
    assert recovered["_store_metadata"]["payload_sha256"] == digest


def test_duplicate_snapshot_rejected(tmp_path):
    store = BrainSnapshotStore(tmp_path / "brain.db", accept_for_test)
    snapshot = Snapshot("snap-001", 1000, 1, Authority.LATCHED)
    store.publish(snapshot, now_ms=1100)

    with pytest.raises(SnapshotRejected):
        store.publish(snapshot, now_ms=1200)


def test_invalid_snapshot_rejected(tmp_path):
    def reject(snapshot, now_ms):
        return Validation(False, ("stale snapshot",))

    store = BrainSnapshotStore(tmp_path / "brain.db", reject)
    snapshot = Snapshot("snap-002", 1000, 1, Authority.LATCHED)

    with pytest.raises(SnapshotRejected, match="stale snapshot"):
        store.publish(snapshot, now_ms=5000)


def test_physical_execution_flag_rejected(tmp_path):
    store = BrainSnapshotStore(tmp_path / "brain.db", accept_for_test)
    snapshot = Snapshot("snap-003", 1000, 1, Authority.CLEAR, physical_execution_enabled=True)

    with pytest.raises(SnapshotRejected):
        store.publish(snapshot, now_ms=1100)


def test_modified_payload_fails_integrity_check(tmp_path):
    path = tmp_path / "brain.db"
    store = BrainSnapshotStore(path, accept_for_test)
    snapshot = Snapshot("snap-004", 1000, 1, Authority.LATCHED)
    store.publish(snapshot, now_ms=1100)

    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE brain_snapshots SET canonical_payload = ? WHERE snapshot_id = ?",
            (json.dumps({"snapshot_id": "tampered"}), "snap-004"),
        )

    with pytest.raises(SnapshotIntegrityError):
        store.get("snap-004")


def test_console_does_not_hide_latched_authority():
    snapshot = Snapshot("snap-005", 1000, 7, Authority.LATCHED, robot_views=(), tasks=(), evidence=())
    output = render_console(snapshot)

    assert "Authority state: LATCHED" in output
    assert "Physical execution: DISABLED" in output
    assert "INFERRED and SIMULATED are not OBSERVED." in output


def test_real_validator_stores_a_clear_snapshot_and_rejects_a_latched_one(tmp_path):
    robot = RobotView(
        robot_id="sim-robot-01",
        feed_status=FeedStatus.LIVE,
        updated_at_ms=1000,
        pose_evidence_class=EvidenceClass.SIMULATED,
        pose_m=(1.0, 2.0, 0.0),
        objects=(),
        unknown_region_count=0,
    )
    clear = BrainSnapshot(
        snapshot_id="live-001",
        created_at_ms=1000,
        robot_views=(robot,),
        tasks=(),
        evidence=(),
        authority_state=AuthorityState.CLEAR,
        authority_revision=1,
        physical_execution_enabled=False,
    )
    latched = BrainSnapshot(
        snapshot_id="live-002",
        created_at_ms=1000,
        robot_views=(robot,),
        tasks=(),
        evidence=(),
        authority_state=AuthorityState.LATCHED,
        authority_revision=1,
    )
    store = BrainSnapshotStore(tmp_path / "brain.db", validate_snapshot)
    store.publish(clear, now_ms=1500)
    rendered = render_console(store.latest())

    assert "pose_class=SIMULATED" in rendered
    assert "Physical execution: DISABLED" in rendered
    with pytest.raises(SnapshotRejected, match="AUTHORITY_INHIBIT_LATCHED"):
        store.publish(latched, now_ms=1500)
