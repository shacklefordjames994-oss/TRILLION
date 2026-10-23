import sqlite3

import pytest

from optimus_swarm.benchmark_journal import AssessmentStatus, BenchmarkJournal, JournalError, sha256_text
from optimus_swarm.kill_switch import HumanAuthorityKillSwitch


def sample_payload():
    return {
        "run_id": "run-001",
        "policy_version": "policy-v1",
        "policy_digest": "a" * 64,
        "scenario_set_digest": "b" * 64,
        "scenario_ids": ["stale-01", "clear-01", "conflict-01"],
        "physical_execution_enabled": False,
    }


def test_round_trip(tmp_path):
    journal = BenchmarkJournal(tmp_path / "runs.sqlite")
    original = sample_payload()
    stored = journal.store_run("run-001", original, "2026-10-22T12:00:00Z")
    restored = journal.read_run("run-001")

    assert restored.payload == original
    assert restored.payload_digest == stored.payload_digest


def test_duplicate_run_rejected(tmp_path):
    journal = BenchmarkJournal(tmp_path / "runs.sqlite")
    payload = sample_payload()
    journal.store_run("run-001", payload, "2026-10-22T12:00:00Z")

    with pytest.raises(JournalError, match="Duplicate"):
        journal.store_run("run-001", payload, "2026-10-22T12:01:00Z")


def test_physical_execution_true_rejected(tmp_path):
    journal = BenchmarkJournal(tmp_path / "runs.sqlite")
    payload = sample_payload()
    payload["physical_execution_enabled"] = True

    with pytest.raises(JournalError):
        journal.store_run("run-001", payload, "2026-10-22T12:00:00Z")


def test_assessment_must_reference_stored_digest(tmp_path):
    journal = BenchmarkJournal(tmp_path / "runs.sqlite")
    journal.store_run("run-001", sample_payload(), "2026-10-22T12:00:00Z")

    with pytest.raises(JournalError, match="wrong run digest"):
        journal.append_assessment("assessment-001", "run-001", "0" * 64, AssessmentStatus.PASS, ())


def test_assessment_is_separate_from_run(tmp_path):
    journal = BenchmarkJournal(tmp_path / "runs.sqlite")
    payload = sample_payload()
    stored = journal.store_run("run-001", payload, "2026-10-22T12:00:00Z")
    assessment = journal.append_assessment(
        "assessment-001",
        "run-001",
        stored.payload_digest,
        AssessmentStatus.INDETERMINATE,
        ("Independent gate not yet connected",),
    )

    assert assessment.status == AssessmentStatus.INDETERMINATE
    assert journal.read_run("run-001").payload == payload
    assert assessment.physical_execution_enabled is False


def test_tampered_payload_and_corrupt_json_are_rejected(tmp_path):
    path = tmp_path / "runs.sqlite"
    journal = BenchmarkJournal(path)
    stored = journal.store_run("run-001", sample_payload(), "2026-10-22T12:00:00Z")

    with sqlite3.connect(path) as db:
        db.execute("UPDATE benchmark_runs SET payload_json = ? WHERE run_id = ?", ('{"run_id":"changed"}', "run-001"))
    with pytest.raises(JournalError, match="digest mismatch"):
        journal.read_run("run-001")

    corrupt = "{"
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE benchmark_runs SET payload_json = ?, payload_digest = ? WHERE run_id = ?",
            (corrupt, sha256_text(corrupt), "run-001"),
        )
    with pytest.raises(JournalError, match="invalid"):
        journal.read_run("run-001")
    assert stored.payload_digest


def test_journal_operations_do_not_clear_the_inhibit(tmp_path):
    switch = HumanAuthorityKillSwitch({"human-001"})
    revision = switch.state.revision
    journal = BenchmarkJournal(tmp_path / "runs.sqlite")
    stored = journal.store_run("run-001", sample_payload(), "2026-10-22T12:00:00Z")
    journal.append_assessment(
        "assessment-001",
        "run-001",
        stored.payload_digest,
        AssessmentStatus.PASS,
        ("Software checks only",),
    )

    assert switch.state.latched is True
    assert switch.state.revision == revision
    assert switch.permits_physical_execution() is False


def test_unavailable_journal_is_not_accepted(tmp_path):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("file")
    with pytest.raises(JournalError, match="unavailable"):
        BenchmarkJournal(blocked / "runs.sqlite")
