from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from optimus_swarm.sensor_consistency import (
    ConsistencyPolicy,
    ConsistencyStatus,
    SensorObservation,
    evaluate_consistency,
)


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    observations: tuple[SensorObservation, ...]
    now_ms: int
    expected_conflict: bool
    expected_stale: bool = False
    expected_invalid: bool = False
    injected_at_ms: int | None = None


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    expected_conflict: bool
    detected_conflict: bool
    expected_stale: bool
    detected_stale: bool
    expected_invalid: bool
    detected_invalid: bool
    detection_latency_ms: int | None
    accepted_for_downstream: bool
    status: str
    physical_execution_permitted: bool = False


@dataclass(frozen=True)
class ValidationMetrics:
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    conflict_precision: float | None
    conflict_recall: float | None
    missed_conflict_rate: float | None
    false_alarm_rate: float | None
    stale_cases: int
    stale_rejections: int
    invalid_cases: int
    invalid_rejections: int
    fail_closed_violations: int
    repeatability_pass: bool


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def run_scenario(scenario: Scenario, *, policy: ConsistencyPolicy = ConsistencyPolicy()) -> ScenarioResult:
    result = evaluate_consistency(scenario.observations, now_ms=scenario.now_ms, policy=policy)
    detected_conflict = result.status == ConsistencyStatus.CONFLICT
    detected_stale = result.status == ConsistencyStatus.STALE
    detected_invalid = result.status == ConsistencyStatus.INVALID
    latency = None
    if detected_conflict and scenario.injected_at_ms is not None:
        latency = max(0, scenario.now_ms - scenario.injected_at_ms)
    return ScenarioResult(
        scenario_id=scenario.scenario_id,
        expected_conflict=scenario.expected_conflict,
        detected_conflict=detected_conflict,
        expected_stale=scenario.expected_stale,
        detected_stale=detected_stale,
        expected_invalid=scenario.expected_invalid,
        detected_invalid=detected_invalid,
        detection_latency_ms=latency,
        accepted_for_downstream=result.accepted_for_downstream,
        status=result.status.value,
        physical_execution_permitted=False,
    )


def calculate_metrics(
    scenarios: Iterable[Scenario],
    results: Iterable[ScenarioResult],
    *,
    repeatability_pass: bool,
) -> ValidationMetrics:
    scenario_list = list(scenarios)
    result_list = list(results)
    if len(scenario_list) != len(result_list):
        raise ValueError("Each scenario must have exactly one result")
    if len({scenario.scenario_id for scenario in scenario_list}) != len(scenario_list):
        raise ValueError("Scenario IDs must be unique")

    true_positive = false_positive = true_negative = false_negative = 0
    stale_cases = stale_rejections = 0
    invalid_cases = invalid_rejections = 0
    fail_closed_violations = 0

    for scenario, result in zip(scenario_list, result_list):
        if scenario.scenario_id != result.scenario_id:
            raise ValueError("Scenario/result order or identity mismatch")
        expected = scenario.expected_conflict
        detected = result.detected_conflict
        if expected and detected:
            true_positive += 1
        elif not expected and detected:
            false_positive += 1
        elif not expected and not detected:
            true_negative += 1
        else:
            false_negative += 1
        if scenario.expected_stale:
            stale_cases += 1
            if not result.accepted_for_downstream:
                stale_rejections += 1
        if scenario.expected_invalid:
            invalid_cases += 1
            if not result.accepted_for_downstream:
                invalid_rejections += 1
        must_block = scenario.expected_conflict or scenario.expected_stale or scenario.expected_invalid
        if must_block and result.accepted_for_downstream:
            fail_closed_violations += 1
        if result.physical_execution_permitted:
            fail_closed_violations += 1

    return ValidationMetrics(
        true_positive=true_positive,
        false_positive=false_positive,
        true_negative=true_negative,
        false_negative=false_negative,
        conflict_precision=_ratio(true_positive, true_positive + false_positive),
        conflict_recall=_ratio(true_positive, true_positive + false_negative),
        missed_conflict_rate=_ratio(false_negative, true_positive + false_negative),
        false_alarm_rate=_ratio(false_positive, false_positive + true_negative),
        stale_cases=stale_cases,
        stale_rejections=stale_rejections,
        invalid_cases=invalid_cases,
        invalid_rejections=invalid_rejections,
        fail_closed_violations=fail_closed_violations,
        repeatability_pass=repeatability_pass,
    )
