from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from optimus_swarm.scenario_validation import Scenario, ScenarioResult, calculate_metrics, run_scenario
from optimus_swarm.sensor_consistency import ConsistencyPolicy


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BenchmarkRun:
    run_id: str
    status: str
    policy_version: str
    policy_digest: str
    scenario_set_digest: str
    required_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]
    skipped_ids: tuple[str, ...]
    indeterminate_ids: tuple[str, ...]
    processing_latency_ns: int
    fail_closed_violations: int
    reasons: tuple[str, ...]
    physical_execution_permitted: bool = False


class BenchmarkRunner:
    """Persistent software-benchmark record. A PASS does not authorize motion."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS benchmark_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    policy_digest TEXT NOT NULL,
                    scenario_set_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at_ns INTEGER NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def record(
        self,
        *,
        run_id: str,
        policy_version: str,
        policy: ConsistencyPolicy,
        scenarios: Iterable[Scenario],
        results: Iterable[ScenarioResult],
        required_ids: Iterable[str],
        skipped_ids: Iterable[str] = (),
        indeterminate_ids: Iterable[str] = (),
        processing_latency_ns: int,
        repeatability_pass: bool,
    ) -> BenchmarkRun:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id is required")
        if not isinstance(policy_version, str) or not policy_version.strip():
            raise ValueError("policy_version is required")

        scenario_list = list(scenarios)
        result_list = list(results)
        required = tuple(required_ids)
        skipped = tuple(skipped_ids)
        indeterminate = tuple(indeterminate_ids)
        present = {result.scenario_id for result in result_list}
        missing = tuple(scenario_id for scenario_id in required if scenario_id not in present)
        reasons: list[str] = []

        if not required:
            reasons.append("NO_REQUIRED_SCENARIOS")
        if missing:
            reasons.append("MISSING_REQUIRED_SCENARIO")
        if skipped:
            reasons.append("SKIPPED_SCENARIO")
        if indeterminate:
            reasons.append("INDETERMINATE_SCENARIO")
        if isinstance(processing_latency_ns, bool) or not isinstance(processing_latency_ns, int) or processing_latency_ns < 0:
            reasons.append("INVALID_PROCESSING_LATENCY")
        if not repeatability_pass:
            reasons.append("REPEATABILITY_FAILED")
        if any(result.physical_execution_permitted for result in result_list):
            reasons.append("PHYSICAL_EXECUTION_ASSERTED")

        violations = 0
        if not any(reason in reasons for reason in ("NO_REQUIRED_SCENARIOS", "MISSING_REQUIRED_SCENARIO")):
            try:
                metrics = calculate_metrics(scenario_list, result_list, repeatability_pass=repeatability_pass)
                violations = metrics.fail_closed_violations
            except ValueError:
                reasons.append("METRIC_INPUT_INVALID")
                violations = 0
        if violations:
            reasons.append("FAIL_CLOSED_VIOLATION")

        evidence_gap = any(
            reason in reasons
            for reason in (
                "NO_REQUIRED_SCENARIOS",
                "MISSING_REQUIRED_SCENARIO",
                "SKIPPED_SCENARIO",
                "INDETERMINATE_SCENARIO",
                "INVALID_PROCESSING_LATENCY",
                "METRIC_INPUT_INVALID",
            )
        )
        if evidence_gap:
            status = "INDETERMINATE"
        elif reasons:
            status = "FAIL"
        else:
            status = "PASS"

        policy_digest = _digest(asdict(policy))
        scenario_digest = _digest(
            [
                {
                    "scenario_id": scenario.scenario_id,
                    "now_ms": scenario.now_ms,
                    "expected_conflict": scenario.expected_conflict,
                    "expected_stale": scenario.expected_stale,
                    "expected_invalid": scenario.expected_invalid,
                    "observations": [asdict(item) for item in scenario.observations],
                }
                for scenario in scenario_list
            ]
        )
        run = BenchmarkRun(
            run_id=run_id.strip(),
            status=status,
            policy_version=policy_version.strip(),
            policy_digest=policy_digest,
            scenario_set_digest=scenario_digest,
            required_ids=required,
            missing_ids=missing,
            skipped_ids=skipped,
            indeterminate_ids=indeterminate,
            processing_latency_ns=processing_latency_ns if isinstance(processing_latency_ns, int) and processing_latency_ns >= 0 else -1,
            fail_closed_violations=violations,
            reasons=tuple(reasons),
            physical_execution_permitted=False,
        )
        payload = _canonical({**asdict(run), "physical_execution_permitted": False})
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO benchmark_runs (
                    run_id, status, policy_version, policy_digest,
                    scenario_set_digest, payload_json, created_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.status,
                    run.policy_version,
                    run.policy_digest,
                    run.scenario_set_digest,
                    payload,
                    time.perf_counter_ns(),
                ),
            )
        return run


def evaluate_run(
    runner: BenchmarkRunner,
    *,
    run_id: str,
    policy_version: str,
    scenarios: list[Scenario],
    required_ids: list[str],
    policy: ConsistencyPolicy = ConsistencyPolicy(),
    skipped_ids: list[str] | None = None,
    indeterminate_ids: list[str] | None = None,
) -> BenchmarkRun:
    """Run the suite twice and time the first pass with a monotonic clock."""
    started = time.perf_counter_ns()
    first = [run_scenario(scenario, policy=policy) for scenario in scenarios]
    elapsed = time.perf_counter_ns() - started
    second = [run_scenario(scenario, policy=policy) for scenario in scenarios]
    return runner.record(
        run_id=run_id,
        policy_version=policy_version,
        policy=policy,
        scenarios=scenarios,
        results=first,
        required_ids=required_ids,
        skipped_ids=skipped_ids or [],
        indeterminate_ids=indeterminate_ids or [],
        processing_latency_ns=elapsed,
        repeatability_pass=first == second,
    )
