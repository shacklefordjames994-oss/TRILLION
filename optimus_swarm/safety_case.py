from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterable


class RunStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INDETERMINATE = "INDETERMINATE"


class ReviewDisposition(str, Enum):
    NOT_REVIEWED = "NOT_REVIEWED"
    ACCEPTED_FOR_REVIEW = "ACCEPTED_FOR_REVIEW"
    REJECTED = "REJECTED"


def _normalize(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def canonical_json(value: object) -> str:
    return json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ScenarioEvidence:
    scenario_id: str
    status: RunStatus
    repeatable: bool
    result_digest: str
    skipped: bool = False


@dataclass(frozen=True)
class BenchmarkEvidence:
    run_id: str
    policy_version: str
    policy_digest: str
    scenario_set_digest: str
    required_scenario_ids: tuple[str, ...]
    scenarios: tuple[ScenarioEvidence, ...]
    software_revision: str
    processing_duration_ns: int
    physical_execution_enabled: bool = False


@dataclass(frozen=True)
class SafetyRequirement:
    requirement_id: str
    hazard_id: str
    description: str
    acceptance_criteria: str
    required_scenario_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReviewRecord:
    requirement_id: str
    reviewer_id: str
    disposition: ReviewDisposition
    evidence_digest: str
    reviewed_at_utc: str


@dataclass(frozen=True)
class GateResult:
    status: RunStatus
    reasons: tuple[str, ...]
    physical_execution_enabled: bool = False


def scenario_set_digest(scenarios: Iterable[ScenarioEvidence]) -> str:
    return digest(
        [
            {
                "scenario_id": scenario.scenario_id,
                "status": scenario.status,
                "repeatable": scenario.repeatable,
                "result_digest": scenario.result_digest,
                "skipped": scenario.skipped,
            }
            for scenario in scenarios
        ]
    )


def validate_benchmark(
    run: BenchmarkEvidence,
    expected_scenario_ids: Iterable[str],
    expected_policy_digest: str,
) -> GateResult:
    reasons: list[str] = []
    expected = tuple(sorted(expected_scenario_ids))
    declared = tuple(sorted(run.required_scenario_ids))
    actual_ids = [scenario.scenario_id for scenario in run.scenarios]

    if not isinstance(run.run_id, str) or not run.run_id.strip():
        reasons.append("Missing run ID")
    if not isinstance(run.software_revision, str) or not run.software_revision.strip():
        reasons.append("Missing software revision")
    if isinstance(run.processing_duration_ns, bool) or not isinstance(run.processing_duration_ns, int) or run.processing_duration_ns < 0:
        reasons.append("Invalid monotonic processing duration")
    if run.physical_execution_enabled:
        reasons.append("Physical execution must remain disabled")
    if len(actual_ids) != len(set(actual_ids)):
        reasons.append("Duplicate scenario IDs")
    if declared != expected:
        reasons.append("Required scenario set mismatch")
    if set(actual_ids) != set(expected):
        reasons.append("Missing or unexpected scenarios")
    if run.policy_digest != expected_policy_digest:
        reasons.append("Policy digest mismatch")
    if not run.scenario_set_digest:
        reasons.append("Missing scenario-set digest")
    elif run.scenario_set_digest != scenario_set_digest(run.scenarios):
        reasons.append("Scenario-set digest mismatch")

    for scenario in run.scenarios:
        if scenario.skipped:
            reasons.append(f"{scenario.scenario_id}: skipped scenario")
        if not scenario.result_digest:
            reasons.append(f"{scenario.scenario_id}: missing result digest")
        if scenario.status == RunStatus.FAIL:
            reasons.append(f"{scenario.scenario_id}: required scenario failed")
        if scenario.status == RunStatus.INDETERMINATE:
            reasons.append(f"{scenario.scenario_id}: indeterminate result")
        if not scenario.repeatable:
            reasons.append(f"{scenario.scenario_id}: repeatability not established")

    if reasons:
        failure_markers = (
            "digest mismatch",
            "scenario failed",
            "Duplicate scenario IDs",
            "Physical execution must remain disabled",
        )
        failed = any(marker in reason for reason in reasons for marker in failure_markers)
        return GateResult(RunStatus.FAIL if failed else RunStatus.INDETERMINATE, tuple(reasons), False)
    return GateResult(RunStatus.PASS, (), False)


def apply_review(gate: GateResult, review: ReviewRecord | None) -> GateResult:
    """A favorable review cannot upgrade FAIL or INDETERMINATE to PASS."""
    reasons = gate.reasons
    if review is not None and review.disposition == ReviewDisposition.ACCEPTED_FOR_REVIEW and gate.status != RunStatus.PASS:
        reasons = reasons + ("Review disposition does not change automated status",)
    return GateResult(gate.status, reasons, False)


def validate_traceability(
    requirement: SafetyRequirement,
    run: BenchmarkEvidence,
    review: ReviewRecord | None,
) -> tuple[str, ...]:
    issues: list[str] = []
    if not requirement.requirement_id.strip():
        issues.append("Missing requirement ID")
    if not requirement.hazard_id.strip():
        issues.append("Missing hazard ID")
    if not requirement.description.strip():
        issues.append("Missing requirement description")
    if not requirement.acceptance_criteria.strip():
        issues.append("Missing acceptance criteria")
    available = {scenario.scenario_id for scenario in run.scenarios}
    missing = set(requirement.required_scenario_ids) - available
    if missing:
        issues.append("Required verification scenarios missing: " + ", ".join(sorted(missing)))
    if review is None:
        issues.append("Independent review record missing")
    else:
        if review.requirement_id != requirement.requirement_id:
            issues.append("Review requirement ID mismatch")
        if not review.reviewer_id.strip():
            issues.append("Missing reviewer identity")
        if review.evidence_digest != digest(asdict(run)):
            issues.append("Review references different evidence")
        if not review.reviewed_at_utc.strip():
            issues.append("Missing review timestamp")
    return tuple(issues)


def build_evidence_package(
    run: BenchmarkEvidence,
    gate: GateResult,
    requirements: Iterable[SafetyRequirement],
    reviews: Iterable[ReviewRecord],
) -> dict:
    review_by_requirement: dict[str, ReviewRecord] = {}
    for review in reviews:
        if review.requirement_id in review_by_requirement:
            raise ValueError("Duplicate review ID")
        review_by_requirement[review.requirement_id] = review

    seen_requirements: set[str] = set()
    traceability = []
    for requirement in requirements:
        if requirement.requirement_id in seen_requirements:
            raise ValueError("Duplicate requirement ID")
        seen_requirements.add(requirement.requirement_id)
        review = review_by_requirement.get(requirement.requirement_id)
        issues = validate_traceability(requirement, run, review)
        traceability.append(
            {
                "requirement": _normalize(asdict(requirement)),
                "review": _normalize(asdict(review)) if review else None,
                "issues": list(issues),
                "review_complete": not issues,
            }
        )

    body = {
        "schema_version": "1.0",
        "run": _normalize(asdict(run)),
        "gate": _normalize(asdict(gate)),
        "traceability": traceability,
        "physical_execution_enabled": False,
        "limitations": [
            "Software evidence only",
            "No physical robot validation implied",
            "No safety certification implied",
            "Digest does not authenticate its source",
        ],
    }
    return {"package": body, "package_digest": digest(body)}


class SafetyCaseJournal:
    """Durable run-id uniqueness. This store does not clear an inhibit."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS safety_cases (
                    run_id TEXT PRIMARY KEY,
                    package_digest TEXT NOT NULL,
                    package_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5.0)

    def commit(self, run_id: str, package: dict) -> None:
        payload = canonical_json(package)
        with self._connect() as db:
            db.execute(
                "INSERT INTO safety_cases (run_id, package_digest, package_json) VALUES (?, ?, ?)",
                (run_id, package["package_digest"], payload),
            )


def commit_trusted_package(journal: SafetyCaseJournal | None, run_id: str, package: dict) -> GateResult:
    status = package["package"]["gate"]["status"]
    if journal is None:
        return GateResult(RunStatus.INDETERMINATE, ("Evidence journal unavailable",), False)
    try:
        journal.commit(run_id, package)
    except sqlite3.IntegrityError:
        raise
    except Exception:
        return GateResult(RunStatus.INDETERMINATE, ("Evidence journal write failed",), False)
    if status == RunStatus.PASS.value:
        return GateResult(RunStatus.PASS, (), False)
    if status == RunStatus.FAIL.value:
        return GateResult(RunStatus.FAIL, ("Stored automated failure",), False)
    return GateResult(RunStatus.INDETERMINATE, ("Stored result is not a pass",), False)
