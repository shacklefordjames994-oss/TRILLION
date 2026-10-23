import json
import sqlite3
from dataclasses import asdict

from optimus_swarm.kill_switch import HumanAuthorityKillSwitch
from optimus_swarm.policy_integrity import TrustedPolicy, policy_digest, verify_policy_integrity, verify_stored_package
from optimus_swarm.safety_case import (
    BenchmarkEvidence,
    ReviewDisposition,
    ReviewRecord,
    RunStatus,
    SafetyCaseJournal,
    SafetyRequirement,
    ScenarioEvidence,
    build_evidence_package,
    scenario_set_digest,
    validate_benchmark,
)


def trusted() -> TrustedPolicy:
    return TrustedPolicy("consistency-policy-1", 0.5, 500, 8.0)


def make_run(policy_digest_value: str) -> BenchmarkEvidence:
    scenario = ScenarioEvidence("conflict-01", RunStatus.PASS, True, "digest-conflict-01")
    scenarios = (scenario,)
    return BenchmarkEvidence(
        run_id="run-1",
        policy_version="consistency-policy-1",
        policy_digest=policy_digest_value,
        scenario_set_digest=scenario_set_digest(scenarios),
        required_scenario_ids=("conflict-01",),
        scenarios=scenarios,
        software_revision="rev-1",
        processing_duration_ns=1000,
        physical_execution_enabled=False,
    )


def test_policy_digest_is_recomputed_from_the_trusted_policy():
    policy = trusted()
    first = policy_digest(policy)
    second = policy_digest(policy)
    changed = policy_digest(TrustedPolicy(policy.policy_version, 0.25, policy.max_age_ms, policy.max_implied_speed_mps))

    assert first == second
    assert len(first) == 64
    assert changed != first


def test_claimed_digest_does_not_override_the_trusted_policy():
    policy = trusted()
    run = make_run("f" * 64)
    switch = HumanAuthorityKillSwitch({"human-001"})
    revision = switch.state.revision

    result = verify_policy_integrity(run, policy, kill_switch=switch)

    assert result.status == RunStatus.FAIL
    assert "Policy digest mismatch" in result.reasons
    assert result.recomputed_policy_digest == policy_digest(policy)
    assert result.inhibit_cleared is False
    assert result.physical_execution_permitted is False
    assert switch.state.latched is True
    assert switch.state.revision == revision


def test_matching_policy_passes_without_clearing_the_inhibit():
    policy = trusted()
    run = make_run(policy_digest(policy))
    switch = HumanAuthorityKillSwitch({"human-001"})
    review = ReviewRecord(
        "req-1",
        "human-001",
        ReviewDisposition.ACCEPTED_FOR_REVIEW,
        "unused",
        "2026-10-22T00:00:00Z",
    )

    result = verify_policy_integrity(run, policy, kill_switch=switch, review=review)

    assert result.status == RunStatus.PASS
    assert switch.state.latched is True
    assert switch.permits_physical_execution() is False
    assert result.inhibit_cleared is False


def test_restart_detects_a_tampered_package(tmp_path):
    policy = trusted()
    run = make_run(policy_digest(policy))
    gate = validate_benchmark(run, ("conflict-01",), policy_digest(policy))
    package = build_evidence_package(
        run,
        gate,
        [SafetyRequirement("req-1", "hazard-collision", "Block a conflict", "Conflict is not admitted", ("conflict-01",))],
        [],
    )
    path = tmp_path / "cases.db"
    SafetyCaseJournal(path).commit(run.run_id, package)

    with sqlite3.connect(path) as db:
        payload = json.loads(db.execute("SELECT package_json FROM safety_cases WHERE run_id = ?", (run.run_id,)).fetchone()[0])
        payload["package"]["run"]["policy_digest"] = "tampered"
        db.execute("UPDATE safety_cases SET package_json = ? WHERE run_id = ?", (json.dumps(payload), run.run_id))

    switch = HumanAuthorityKillSwitch({"human-001"})
    reopened = verify_stored_package(path, run.run_id, policy, kill_switch=switch)

    assert reopened.status == RunStatus.FAIL
    assert "Stored package digest mismatch" in reopened.reasons
    assert switch.state.latched is True
    assert switch.permits_physical_execution() is False


def test_unmodified_package_survives_reload(tmp_path):
    policy = trusted()
    run = make_run(policy_digest(policy))
    gate = validate_benchmark(run, ("conflict-01",), policy_digest(policy))
    package = build_evidence_package(run, gate, [], [])
    path = tmp_path / "cases.db"
    SafetyCaseJournal(path).commit(run.run_id, package)

    switch = HumanAuthorityKillSwitch({"human-001"})
    reopened = verify_stored_package(path, run.run_id, policy, kill_switch=switch)

    assert reopened.status == RunStatus.PASS
    assert reopened.recomputed_policy_digest == policy_digest(policy)
    assert switch.state.revision == 1
    assert switch.state.latched is True
