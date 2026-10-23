from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import hmac
import json
from typing import Any

from optimus_swarm.benchmark_journal import BenchmarkJournal, JournalError


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class ScenarioRecord:
    scenario_id: str
    outcome: str
    repeatable: bool
    result_digest: str


@dataclass(frozen=True)
class ScenarioExecution:
    scenario_id: str
    execution_id: str
    input_digest: str
    policy_digest: str
    output_digest: str
    outcome: str
    processing_duration_ns: int


@dataclass(frozen=True)
class GateAssessment:
    status: GateStatus
    reasons: tuple[str, ...]
    physical_execution_enabled: bool = False


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def scenario_set_digest(required_ids: tuple[str, ...]) -> str:
    return sha256_value(sorted(required_ids))


def _same(left: object, right: object) -> bool:
    if not isinstance(left, str) or not isinstance(right, str) or len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def assess_benchmark(
    *,
    run_id: str,
    policy_digest: str,
    expected_policy_digest: str,
    required_scenario_ids: tuple[str, ...],
    declared_scenario_set_digest: str,
    scenarios: tuple[ScenarioRecord, ...],
    physical_execution_enabled: bool,
) -> GateAssessment:
    """Recompute a gate result. A stored status label is not an input."""
    reasons: list[str] = []
    integrity_failure = False
    scenario_failure = False

    if not isinstance(run_id, str) or not run_id.strip():
        reasons.append("Missing run ID")
    if physical_execution_enabled is not False:
        reasons.append("Physical execution invariant violated")
        integrity_failure = True
    if not _same(policy_digest, expected_policy_digest):
        reasons.append("Policy digest mismatch")
        integrity_failure = True
    if len(required_scenario_ids) != len(set(required_scenario_ids)):
        reasons.append("Duplicate required scenario IDs")
        integrity_failure = True
    actual_ids = [record.scenario_id for record in scenarios]
    if len(actual_ids) != len(set(actual_ids)):
        reasons.append("Duplicate scenario records")
        integrity_failure = True
    if not all(isinstance(scenario_id, str) and scenario_id.strip() for scenario_id in required_scenario_ids):
        reasons.append("Invalid required scenario ID")
        integrity_failure = True

    try:
        expected_digest = scenario_set_digest(required_scenario_ids)
    except TypeError:
        expected_digest = ""
        reasons.append("Invalid required scenario ID")
        integrity_failure = True
    if not _same(declared_scenario_set_digest, expected_digest):
        reasons.append("Scenario-set digest mismatch")
        integrity_failure = True

    expected = set(required_scenario_ids)
    actual = set(actual_ids)
    if expected - actual:
        reasons.append("Missing scenarios: " + ", ".join(sorted(expected - actual)))
    if actual - expected:
        reasons.append("Unexpected scenarios: " + ", ".join(sorted(str(item) for item in actual - expected)))

    for record in scenarios:
        if record.scenario_id not in expected:
            continue
        if not isinstance(record.result_digest, str) or not record.result_digest:
            reasons.append(f"{record.scenario_id}: missing result digest")
            integrity_failure = True
            continue
        if record.outcome == "FAIL":
            reasons.append(f"{record.scenario_id}: acceptance criterion failed")
            scenario_failure = True
        elif record.outcome != "PASS":
            reasons.append(f"{record.scenario_id}: outcome not established")
        elif record.repeatable is not True:
            reasons.append(f"{record.scenario_id}: repeatability not established")

    if integrity_failure or scenario_failure:
        status = GateStatus.FAIL
    elif reasons:
        status = GateStatus.INDETERMINATE
    else:
        status = GateStatus.PASS
    return GateAssessment(status, tuple(reasons), False)


def executions_repeatable(first: ScenarioExecution, second: ScenarioExecution) -> bool:
    """Exact reproducibility of two passes. This is not evidence about the physical world."""
    if first.execution_id == second.execution_id or first.scenario_id != second.scenario_id:
        return False
    if (
        isinstance(first.processing_duration_ns, bool)
        or isinstance(second.processing_duration_ns, bool)
        or not isinstance(first.processing_duration_ns, int)
        or not isinstance(second.processing_duration_ns, int)
        or first.processing_duration_ns < 0
        or second.processing_duration_ns < 0
    ):
        return False
    return (
        _same(first.input_digest, second.input_digest)
        and _same(first.policy_digest, second.policy_digest)
        and _same(first.output_digest, second.output_digest)
        and first.outcome == second.outcome
    )


def recover_from_journal(
    journal: BenchmarkJournal,
    run_id: str,
    expected_policy_digest: str,
    *,
    kill_switch=None,
) -> GateAssessment:
    """Reload a stored run and recompute the gate. This does not reset an inhibit."""
    revision = None if kill_switch is None else kill_switch.state.revision
    latched = None if kill_switch is None else kill_switch.state.latched
    try:
        stored = journal.read_run(run_id)
    except JournalError as exc:
        message = str(exc)
        status = GateStatus.FAIL if "digest" in message or "Physical" in message else GateStatus.INDETERMINATE
        assessment = GateAssessment(status, (message,), False)
    else:
        payload = stored.payload
        raw_scenarios = payload.get("scenarios")
        if not isinstance(raw_scenarios, list) or not raw_scenarios:
            assessment = GateAssessment(GateStatus.INDETERMINATE, ("Scenario evidence missing after restart",), False)
        else:
            try:
                scenarios = tuple(
                    ScenarioRecord(
                        item["scenario_id"],
                        item["outcome"],
                        item["repeatable"],
                        item["result_digest"],
                    )
                    for item in raw_scenarios
                )
                required = tuple(payload.get("required_scenario_ids", ()))
                assessment = assess_benchmark(
                    run_id=run_id,
                    policy_digest=payload.get("policy_digest", ""),
                    expected_policy_digest=expected_policy_digest,
                    required_scenario_ids=required,
                    declared_scenario_set_digest=payload.get("scenario_set_digest", ""),
                    scenarios=scenarios,
                    physical_execution_enabled=payload.get("physical_execution_enabled", True),
                )
            except (KeyError, TypeError):
                assessment = GateAssessment(GateStatus.INDETERMINATE, ("Stored scenario evidence is incomplete",), False)
        stored_label = payload.get("status")
        if stored_label == "PASS" and assessment.status != GateStatus.PASS:
            assessment = GateAssessment(
                assessment.status,
                assessment.reasons + ("Stored PASS label was not trusted",),
                False,
            )
    if kill_switch is not None:
        state = kill_switch.state
        if state.revision != revision or state.latched != latched or kill_switch.permits_physical_execution():
            return GateAssessment(GateStatus.FAIL, assessment.reasons + ("Inhibit changed during recovery",), False)
    return assessment
