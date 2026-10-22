import json
import sqlite3

from optimus_swarm.adaptive_event_log import AdaptiveEventLog, publish_logged_decision
from optimus_swarm.adaptive_response import AdaptiveDecision, ResponseGrade
from optimus_swarm.response_stabilizer import ResponseStabilizer


def decision(grade, accepted=True):
    return AdaptiveDecision(
        accepted=accepted,
        risk_score=0.1 if accepted else None,
        response_grade=grade,
        time_to_contact_s=None,
        adjusted_distance_m=5.0 if accepted else None,
        reasons=(),
        physical_execution_permitted=False,
    )


def test_risk_escalates_immediately():
    stabilizer = ResponseStabilizer(downgrade_samples=3)
    result = stabilizer.update(decision(ResponseGrade.G1_CAUTION))
    assert result.response_grade == ResponseGrade.G1_CAUTION
    assert result.physical_execution_permitted is False


def test_downgrade_requires_consecutive_samples():
    stabilizer = ResponseStabilizer(downgrade_samples=3)
    assert stabilizer.update(decision(ResponseGrade.G2_HUMAN_REVIEW)).response_grade == ResponseGrade.G2_HUMAN_REVIEW
    for _ in range(2):
        result = stabilizer.update(decision(ResponseGrade.G1_CAUTION))
        assert result.response_grade == ResponseGrade.G2_HUMAN_REVIEW
        assert "DOWNGRADE_HELD_BY_HYSTERESIS" in result.reasons
    result = stabilizer.update(decision(ResponseGrade.G1_CAUTION))
    assert result.response_grade == ResponseGrade.G1_CAUTION


def test_critical_grade_remains_latched():
    stabilizer = ResponseStabilizer(downgrade_samples=1)
    stabilizer.update(decision(ResponseGrade.G3_CRITICAL_INHIBIT))
    result = stabilizer.update(decision(ResponseGrade.G0_MONITOR))
    assert result.response_grade == ResponseGrade.G3_CRITICAL_INHIBIT
    assert result.critical_latched is True
    assert result.physical_execution_permitted is False


def test_invalid_decision_fails_closed():
    stabilizer = ResponseStabilizer()
    result = stabilizer.update(decision(ResponseGrade.G0_MONITOR, accepted=False))
    assert result.response_grade == ResponseGrade.G4_DATA_INVALID
    assert result.physical_execution_permitted is False


def test_critical_latch_cannot_be_reset_by_this_component():
    stabilizer = ResponseStabilizer()
    stabilizer.update(decision(ResponseGrade.G3_CRITICAL_INHIBIT))
    assert not hasattr(stabilizer, "reset")
    assert stabilizer.update(decision(ResponseGrade.G0_MONITOR)).critical_latched


def test_event_log_retains_policy_and_simulated_evidence(tmp_path):
    log = AdaptiveEventLog(tmp_path / "adaptive.db")
    snapshot = {"evidence_class": "SIMULATED", "distance_m": 3.0}
    recorded = {"response_grade": "G0_MONITOR", "physical_execution_permitted": False}
    first = log.append(
        event_id="event-1",
        policy_version="adaptive-policy-1",
        input_snapshot=snapshot,
        decision=recorded,
        evidence_ids=["evidence-b", "evidence-a"],
    )
    second = log.append(
        event_id="event-2",
        policy_version="adaptive-policy-1",
        input_snapshot=snapshot,
        decision=recorded,
        evidence_ids=["evidence-a"],
    )

    with sqlite3.connect(tmp_path / "adaptive.db") as db:
        rows = db.execute(
            "SELECT event_id, policy_version, payload_json, previous_digest, event_digest FROM adaptive_events ORDER BY rowid"
        ).fetchall()

    payload = json.loads(rows[0][2])
    assert rows[0][1] == "adaptive-policy-1"
    assert payload["input_snapshot"]["evidence_class"] == "SIMULATED"
    assert payload["evidence_ids"] == ["evidence-a", "evidence-b"]
    assert payload["physical_execution_permitted"] is False
    assert rows[0][3] == "GENESIS"
    assert rows[0][4] == first
    assert rows[1][3] == first
    assert rows[1][4] == second


def test_duplicate_event_id_is_rejected(tmp_path):
    log = AdaptiveEventLog(tmp_path / "adaptive.db")
    kwargs = dict(
        event_id="event-1",
        policy_version="adaptive-policy-1",
        input_snapshot={"evidence_class": "INFERRED"},
        decision={"response_grade": "G1_CAUTION"},
        evidence_ids=["evidence-1"],
    )
    log.append(**kwargs)
    try:
        log.append(**kwargs)
    except sqlite3.IntegrityError:
        rejected = True
    else:
        rejected = False
    assert rejected is True


def test_failed_log_write_blocks_the_decision(tmp_path):
    log = AdaptiveEventLog(tmp_path / "adaptive.db")

    def broken_append(**kwargs):
        raise sqlite3.OperationalError("disk full")

    log.append = broken_append
    result = publish_logged_decision(
        log,
        event_id="event-9",
        policy_version="adaptive-policy-1",
        input_snapshot={"evidence_class": "OBSERVED"},
        decision={"response_grade": "G0_MONITOR"},
        evidence_ids=["evidence-9"],
    )
    assert result["accepted"] is False
    assert result["response_grade"] == "G4_DATA_INVALID"
    assert result["reason"] == "AUDIT_WRITE_FAILED"
    assert result["physical_execution_permitted"] is False
