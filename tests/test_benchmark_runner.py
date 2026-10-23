import sqlite3

import pytest

from optimus_swarm.benchmark_runner import BenchmarkRunner, evaluate_run
from optimus_swarm.scenario_validation import Scenario
from optimus_swarm.sensor_consistency import SensorObservation


def observation(oid, source, x, captured=1000, received=1010):
    return SensorObservation(oid, source, "target-1", "world-v1", captured, received, (x, 0.0, 0.0), 0.05)


def suite():
    return [
        Scenario("consistent-01", (observation("a1", "camera", 1.0), observation("b1", "depth", 1.1)), 1020, False),
        Scenario("conflict-01", (observation("a2", "camera", 1.0), observation("b2", "depth", 2.0)), 1020, True, injected_at_ms=1000),
        Scenario("stale-01", (observation("a3", "camera", 1.0, captured=100, received=110),), 2000, False, True),
    ]


def test_complete_run_passes_without_authorizing_motion(tmp_path):
    scenarios = suite()
    run = evaluate_run(
        BenchmarkRunner(tmp_path / "bench.db"),
        run_id="run-1",
        policy_version="consistency-policy-1",
        scenarios=scenarios,
        required_ids=[scenario.scenario_id for scenario in scenarios],
    )

    assert run.status == "PASS"
    assert run.fail_closed_violations == 0
    assert run.processing_latency_ns >= 0
    assert run.physical_execution_permitted is False
    assert len(run.policy_digest) == 64
    assert len(run.scenario_set_digest) == 64


def test_missing_skipped_or_indeterminate_is_not_a_pass(tmp_path):
    scenarios = suite()
    runner = BenchmarkRunner(tmp_path / "bench.db")
    required = [scenario.scenario_id for scenario in scenarios]

    missing = evaluate_run(
        runner,
        run_id="run-missing",
        policy_version="consistency-policy-1",
        scenarios=scenarios[:2],
        required_ids=required,
    )
    skipped = evaluate_run(
        runner,
        run_id="run-skipped",
        policy_version="consistency-policy-1",
        scenarios=scenarios,
        required_ids=required,
        skipped_ids=["conflict-01"],
    )
    indeterminate = evaluate_run(
        runner,
        run_id="run-indeterminate",
        policy_version="consistency-policy-1",
        scenarios=scenarios,
        required_ids=required,
        indeterminate_ids=["stale-01"],
    )

    assert missing.status == "INDETERMINATE"
    assert missing.missing_ids == ("stale-01",)
    assert skipped.status == "INDETERMINATE"
    assert indeterminate.status == "INDETERMINATE"
    assert all(run.physical_execution_permitted is False for run in (missing, skipped, indeterminate))


def test_duplicate_run_id_is_rejected(tmp_path):
    runner = BenchmarkRunner(tmp_path / "bench.db")
    scenarios = suite()
    kwargs = dict(
        run_id="run-1",
        policy_version="consistency-policy-1",
        scenarios=scenarios,
        required_ids=[scenario.scenario_id for scenario in scenarios],
    )
    evaluate_run(runner, **kwargs)
    with pytest.raises(sqlite3.IntegrityError):
        evaluate_run(runner, **kwargs)
