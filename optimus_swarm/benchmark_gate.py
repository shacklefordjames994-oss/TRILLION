from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from hashlib import sha256
import json
import math
from typing import Callable


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class BenchmarkEvidence:
    benchmark_id: str
    benchmark_version: str
    source: str
    created_at_ms: int
    seed: int
    test_count: int
    passed_tests: int
    failed_tests: int
    skipped_tests: int
    precision: float | None
    recall: float | None
    mean_localization_error_m: float | None
    max_localization_error_m: float | None
    physical_execution_enabled: bool
    model_version: str
    evidence_digest: str = ""

    def payload(self) -> dict:
        data = asdict(self)
        data.pop("evidence_digest", None)
        return data

    def calculate_digest(self) -> str:
        canonical = json.dumps(
            self.payload(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return sha256(canonical).hexdigest()

    def with_digest(self) -> "BenchmarkEvidence":
        return replace(self, evidence_digest=self.calculate_digest())


@dataclass(frozen=True)
class GatePolicy:
    max_age_ms: int = 300_000
    min_tests: int = 1
    min_precision: float = 0.95
    min_recall: float = 0.95
    max_mean_error_m: float = 0.10
    max_error_m: float = 0.25
    require_zero_skipped: bool = True


@dataclass(frozen=True)
class GateResult:
    status: GateStatus
    reasons: tuple[str, ...]
    evidence_digest: str
    physical_execution_authorized: bool = False


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def evaluate_benchmark(
    evidence: BenchmarkEvidence,
    policy: GatePolicy,
    *,
    now_ms: int,
    verify_integrity: Callable[[], bool],
) -> GateResult:
    """
    Software benchmark gate only.

    verify_integrity must independently verify the external evidence
    store or ledger. A self-computed SHA-256 digest alone does not
    establish authenticity or tamper resistance.
    """
    failures: list[str] = []
    unknowns: list[str] = []

    if evidence.source != "SIMULATION_ONLY":
        failures.append("SOURCE_NOT_SIMULATION_ONLY")

    if evidence.physical_execution_enabled:
        failures.append("PHYSICAL_EXECUTION_FLAG_MUST_BE_FALSE")

    if not evidence.benchmark_id or not evidence.benchmark_version:
        unknowns.append("BENCHMARK_IDENTITY_MISSING")

    if not evidence.model_version:
        unknowns.append("MODEL_VERSION_MISSING")

    if evidence.created_at_ms <= 0 or now_ms < evidence.created_at_ms:
        unknowns.append("INVALID_OR_FUTURE_TIMESTAMP")
    elif now_ms - evidence.created_at_ms > policy.max_age_ms:
        unknowns.append("EVIDENCE_STALE")

    counts = (
        evidence.test_count,
        evidence.passed_tests,
        evidence.failed_tests,
        evidence.skipped_tests,
    )

    if any(not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in counts):
        failures.append("INVALID_TEST_COUNTS")
    elif evidence.test_count != evidence.passed_tests + evidence.failed_tests + evidence.skipped_tests:
        failures.append("TEST_COUNTS_DO_NOT_RECONCILE")
    elif evidence.test_count < policy.min_tests:
        unknowns.append("INSUFFICIENT_TEST_COVERAGE")

    if evidence.failed_tests > 0:
        failures.append("TEST_FAILURES_PRESENT")

    if policy.require_zero_skipped and evidence.skipped_tests > 0:
        unknowns.append("SKIPPED_TESTS_PRESENT")

    metrics = (
        ("precision", evidence.precision, policy.min_precision),
        ("recall", evidence.recall, policy.min_recall),
        ("mean_localization_error_m", evidence.mean_localization_error_m, policy.max_mean_error_m),
        ("max_localization_error_m", evidence.max_localization_error_m, policy.max_error_m),
    )

    for name, value, threshold in metrics:
        if value is None or not _is_finite_number(value):
            unknowns.append(f"METRIC_MISSING_OR_INVALID:{name}")
            continue

        if name in ("precision", "recall") and not 0.0 <= value <= 1.0:
            failures.append(f"METRIC_OUT_OF_RANGE:{name}")
            continue

        if name in ("precision", "recall"):
            if value < threshold:
                failures.append(f"THRESHOLD_FAILED:{name}")
        elif value < 0:
            failures.append(f"METRIC_OUT_OF_RANGE:{name}")
        elif value > threshold:
            failures.append(f"THRESHOLD_FAILED:{name}")

    calculated = evidence.calculate_digest()
    if not evidence.evidence_digest or evidence.evidence_digest != calculated:
        failures.append("EVIDENCE_DIGEST_MISMATCH")

    try:
        if verify_integrity() is not True:
            unknowns.append("INTEGRITY_VERIFICATION_FAILED")
    except Exception:
        unknowns.append("INTEGRITY_VERIFICATION_ERROR")

    if failures:
        status = GateStatus.FAIL
    elif unknowns:
        status = GateStatus.INDETERMINATE
    else:
        status = GateStatus.PASS

    return GateResult(
        status=status,
        reasons=tuple(failures + unknowns),
        evidence_digest=calculated,
        physical_execution_authorized=False,
    )
