from dataclasses import replace

from optimus_swarm.benchmark_journal import BenchmarkJournal
from optimus_swarm.independent_gate import (
    GateStatus,
    ScenarioExecution,
    ScenarioRecord,
    assess_benchmark,
    executions_repeatable,
    recover_from_journal,
    scenario_set_digest,
)
from optimus_swarm.kill_switch import HumanAuthorityKillSwitch

REQUIRED = ("clear-01", "conflict-01", "stale-01")
POLICY = "a" * 64


def records():
    return tuple(
        ScenarioRecord(scenario_id, "PASS", True, str(index + 1) * 64) for index, scenario_id in enumerate(REQUIRED)
    )


def evaluate(scenarios=None, **overrides):
    args = {
        "run_id": "run-001",
        "policy_digest": POLICY,
        "expected_policy_digest": POLICY,
        "required_scenario_ids": REQUIRED,
        "declared_scenario_set_digest": scenario_set_digest(REQUIRED),
        "scenarios": records() if scenarios is None else scenarios,
        "physical_execution_enabled": False,
    }
    args.update(overrides)
    return assess_benchmark(**args)


def test_complete_scenario_set_passes():
    result = evaluate()
    assert result.status == GateStatus.PASS
    assert result.physical_execution_enabled is False


def test_missing_scenario_is_indeterminate():
    assert evaluate(records()[:-1]).status == GateStatus.INDETERMINATE


def test_skipped_scenario_is_indeterminate():
    changed = list(records())
    changed[0] = replace(changed[0], outcome="SKIPPED")
    assert evaluate(tuple(changed)).status == GateStatus.INDETERMINATE


def test_failed_scenario_fails_gate():
    changed = list(records())
    changed[0] = replace(changed[0], outcome="FAIL")
    assert evaluate(tuple(changed)).status == GateStatus.FAIL


def test_policy_tampering_fails_gate():
    assert evaluate(policy_digest="b" * 64).status == GateStatus.FAIL


def test_scenario_set_tampering_fails_gate():
    assert evaluate(declared_scenario_set_digest="0" * 64).status == GateStatus.FAIL


def test_duplicate_scenario_fails_gate():
    assert evaluate(records() + (records()[0],)).status == GateStatus.FAIL


def test_nonrepeatable_scenario_is_indeterminate():
    changed = list(records())
    changed[0] = replace(changed[0], repeatable=False)
    assert evaluate(tuple(changed)).status == GateStatus.INDETERMINATE


def test_physical_execution_true_fails_closed():
    result = evaluate(physical_execution_enabled=True)
    assert result.status == GateStatus.FAIL
    assert result.physical_execution_enabled is False


def _execution(execution_id: str, output: str = "out", outcome: str = "PASS") -> ScenarioExecution:
    return ScenarioExecution("clear-01", execution_id, "in", POLICY, output, outcome, 1000)


def test_repeatability_requires_two_distinct_matching_passes():
    assert executions_repeatable(_execution("pass-1"), _execution("pass-2")) is True
    assert executions_repeatable(_execution("pass-1"), _execution("pass-1")) is False
    assert executions_repeatable(_execution("pass-1"), _execution("pass-2", output="other")) is False
    assert executions_repeatable(_execution("pass-1"), _execution("pass-2", outcome="FAIL")) is False


def test_restart_recomputes_the_gate_and_does_not_clear_the_inhibit(tmp_path):
    journal = BenchmarkJournal(tmp_path / "runs.sqlite")
    switch = HumanAuthorityKillSwitch({"human-001"})
    payload = {
        "run_id": "run-001",
        "policy_digest": POLICY,
        "scenario_set_digest": scenario_set_digest(REQUIRED),
        "required_scenario_ids": list(REQUIRED),
        "scenarios": [
            {
                "scenario_id": record.scenario_id,
                "outcome": "FAIL" if record.scenario_id == "conflict-01" else "PASS",
                "repeatable": True,
                "result_digest": record.result_digest,
            }
            for record in records()
        ],
        "status": "PASS",
        "physical_execution_enabled": False,
    }
    journal.store_run("run-001", payload, "2026-10-22T12:00:00Z")
    revision = switch.state.revision

    recovered = recover_from_journal(journal, "run-001", POLICY, kill_switch=switch)

    assert recovered.status == GateStatus.FAIL
    assert "Stored PASS label was not trusted" in recovered.reasons
    assert recovered.physical_execution_enabled is False
    assert switch.state.latched is True
    assert switch.state.revision == revision
    assert switch.permits_physical_execution() is False


def test_missing_evidence_after_restart_is_indeterminate(tmp_path):
    journal = BenchmarkJournal(tmp_path / "runs.sqlite")
    journal.store_run(
        "run-001",
        {
            "run_id": "run-001",
            "policy_digest": POLICY,
            "scenario_ids": ["clear-01"],
            "physical_execution_enabled": False,
        },
        "2026-10-22T12:00:00Z",
    )
    switch = HumanAuthorityKillSwitch({"human-001"})
    recovered = recover_from_journal(journal, "run-001", POLICY, kill_switch=switch)

    assert recovered.status == GateStatus.INDETERMINATE
    assert recovered.reasons == ("Scenario evidence missing after restart",)
    assert switch.state.latched is True
    assert switch.permits_physical_execution() is False
