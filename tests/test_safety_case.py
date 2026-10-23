import sqlite3

import pytest

from optimus_swarm.safety_case import (
    BenchmarkEvidence,
    ReviewDisposition,
    ReviewRecord,
    RunStatus,
    SafetyCaseJournal,
    SafetyRequirement,
    ScenarioEvidence,
    apply_review,
    build_evidence_package,
    commit_trusted_package,
    digest,
    scenario_set_digest,
    validate_benchmark,
    validate_traceability,
)
from dataclasses import asdict


def scenario(scenario_id, status=RunStatus.PASS, skipped=False):
    return ScenarioEvidence(scenario_id, status, True, f"digest-{scenario_id}", skipped)


def make_run(scenarios, *, policy_digest="policy-digest", physical=False, scenario_digest=None, run_id="run-1"):
    items = tuple(scenarios)
    return BenchmarkEvidence(
        run_id=run_id,
        policy_version="consistency-policy-1",
        policy_digest=policy_digest,
        scenario_set_digest=scenario_set_digest(items) if scenario_digest is None else scenario_digest,
        required_scenario_ids=tuple(item.scenario_id for item in items),
        scenarios=items,
        software_revision="rev-1",
        processing_duration_ns=1000,
        physical_execution_enabled=physical,
    )


def test_all_required_scenarios_pass():
    run = make_run((scenario("consistent-01"), scenario("conflict-01"), scenario("stale-01")))
    gate = validate_benchmark(run, ("conflict-01", "consistent-01", "stale-01"), "policy-digest")
    assert gate.status == RunStatus.PASS
    assert gate.physical_execution_enabled is False


def test_missing_or_skipped_scenario_is_indeterminate():
    present = make_run((scenario("consistent-01"),))
    missing = validate_benchmark(present, ("consistent-01", "conflict-01"), "policy-digest")
    skipped_run = make_run((scenario("consistent-01"), scenario("conflict-01", skipped=True)))
    skipped = validate_benchmark(skipped_run, ("consistent-01", "conflict-01"), "policy-digest")

    assert missing.status == RunStatus.INDETERMINATE
    assert skipped.status == RunStatus.INDETERMINATE
    assert missing.physical_execution_enabled is False


def test_failed_scenario_and_policy_mismatch_fail():
    failed = make_run((scenario("conflict-01", status=RunStatus.FAIL),))
    mismatch = make_run((scenario("conflict-01"),), policy_digest="other-digest")

    assert validate_benchmark(failed, ("conflict-01",), "policy-digest").status == RunStatus.FAIL
    assert validate_benchmark(mismatch, ("conflict-01",), "policy-digest").status == RunStatus.FAIL


def test_duplicate_scenario_ids_fail():
    run = make_run((scenario("conflict-01"), scenario("conflict-01")))
    gate = validate_benchmark(run, ("conflict-01",), "policy-digest")
    assert gate.status == RunStatus.FAIL
    assert "Duplicate scenario IDs" in gate.reasons


def test_review_cannot_turn_a_failure_into_a_pass():
    run = make_run((scenario("conflict-01", status=RunStatus.FAIL),))
    gate = validate_benchmark(run, ("conflict-01",), "policy-digest")
    review = ReviewRecord("req-1", "human-001", ReviewDisposition.ACCEPTED_FOR_REVIEW, digest(asdict(run)), "2026-10-22T00:00:00Z")
    reviewed = apply_review(gate, review)
    assert gate.status == RunStatus.FAIL
    assert reviewed.status == RunStatus.FAIL
    assert reviewed.physical_execution_enabled is False


def test_review_of_different_evidence_is_incomplete():
    run = make_run((scenario("conflict-01"),))
    requirement = SafetyRequirement("req-1", "hazard-collision", "Block a conflict", "Conflict is not admitted", ("conflict-01",))
    review = ReviewRecord("req-1", "human-001", ReviewDisposition.ACCEPTED_FOR_REVIEW, "different-digest", "2026-10-22T00:00:00Z")
    issues = validate_traceability(requirement, run, review)
    assert "Review references different evidence" in issues


def test_physical_execution_flag_is_rejected():
    run = make_run((scenario("conflict-01"),), physical=True)
    gate = validate_benchmark(run, ("conflict-01",), "policy-digest")
    assert gate.status == RunStatus.FAIL
    assert gate.physical_execution_enabled is False


def test_duplicate_run_id_is_rejected_and_missing_journal_is_not_a_pass(tmp_path):
    run = make_run((scenario("conflict-01"),))
    gate = validate_benchmark(run, ("conflict-01",), "policy-digest")
    package = build_evidence_package(
        run,
        gate,
        [SafetyRequirement("req-1", "hazard-collision", "Block a conflict", "Conflict is not admitted", ("conflict-01",))],
        [ReviewRecord("req-1", "human-001", ReviewDisposition.ACCEPTED_FOR_REVIEW, digest(asdict(run)), "2026-10-22T00:00:00Z")],
    )
    assert package["package"]["physical_execution_enabled"] is False
    unavailable = commit_trusted_package(None, run.run_id, package)
    assert unavailable.status == RunStatus.INDETERMINATE

    journal = SafetyCaseJournal(tmp_path / "cases.db")
    stored = commit_trusted_package(journal, run.run_id, package)
    assert stored.status == RunStatus.PASS
    with pytest.raises(sqlite3.IntegrityError):
        commit_trusted_package(journal, run.run_id, package)
