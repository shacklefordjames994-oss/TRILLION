import json
from dataclasses import replace

from optimus_swarm.benchmark_gate import BenchmarkEvidence, GatePolicy, GateStatus, evaluate_benchmark
from optimus_swarm.gate_report import review_benchmark


def valid_evidence():
    return BenchmarkEvidence(
        benchmark_id="warehouse-rgbd-v1",
        benchmark_version="0.1",
        source="SIMULATION_ONLY",
        created_at_ms=100_000,
        seed=7,
        test_count=10,
        passed_tests=10,
        failed_tests=0,
        skipped_tests=0,
        precision=0.99,
        recall=0.98,
        mean_localization_error_m=0.02,
        max_localization_error_m=0.04,
        physical_execution_enabled=False,
        model_version="synthetic-stub-0.1",
    ).with_digest()


def evaluate(evidence, integrity=True):
    return evaluate_benchmark(
        evidence,
        GatePolicy(),
        now_ms=101_000,
        verify_integrity=lambda: integrity,
    )


def test_valid_report_passes_software_gate():
    result = evaluate(valid_evidence())
    assert result.status == GateStatus.PASS
    assert result.physical_execution_authorized is False


def test_digest_tampering_fails():
    evidence = valid_evidence()
    altered = replace(evidence, recall=0.50)
    result = evaluate(altered)

    assert result.status == GateStatus.FAIL
    assert "EVIDENCE_DIGEST_MISMATCH" in result.reasons


def test_stale_evidence_is_indeterminate():
    evidence = valid_evidence()
    result = evaluate_benchmark(
        evidence,
        GatePolicy(max_age_ms=500),
        now_ms=101_000,
        verify_integrity=lambda: True,
    )

    assert result.status == GateStatus.INDETERMINATE
    assert "EVIDENCE_STALE" in result.reasons


def test_failed_test_fails_gate():
    evidence = replace(
        valid_evidence(),
        passed_tests=9,
        failed_tests=1,
        evidence_digest="",
    ).with_digest()

    result = evaluate(evidence)
    assert result.status == GateStatus.FAIL
    assert "TEST_FAILURES_PRESENT" in result.reasons


def test_missing_metric_is_indeterminate():
    evidence = replace(
        valid_evidence(),
        precision=None,
        evidence_digest="",
    ).with_digest()

    result = evaluate(evidence)
    assert result.status == GateStatus.INDETERMINATE
    assert "METRIC_MISSING_OR_INVALID:precision" in result.reasons


def test_integrity_exception_fails_closed_to_indeterminate():
    evidence = valid_evidence()

    def broken_verifier():
        raise RuntimeError("ledger unavailable")

    result = evaluate_benchmark(
        evidence,
        GatePolicy(),
        now_ms=101_000,
        verify_integrity=broken_verifier,
    )

    assert result.status == GateStatus.INDETERMINATE
    assert "INTEGRITY_VERIFICATION_ERROR" in result.reasons


def test_physical_execution_flag_is_rejected():
    evidence = replace(
        valid_evidence(),
        physical_execution_enabled=True,
        evidence_digest="",
    ).with_digest()

    result = evaluate(evidence)
    assert result.status == GateStatus.FAIL
    assert result.physical_execution_authorized is False


def test_json_report_records_scope_and_never_authorizes_motion(tmp_path):
    path = tmp_path / "benchmark-gate.json"
    result = review_benchmark(
        valid_evidence(),
        now_ms=101_000,
        integrity_verifier=lambda: True,
        output_path=str(path),
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert result.status == GateStatus.PASS
    assert payload["gate_status"] == "PASS"
    assert payload["reasons"] == []
    assert payload["evidence_digest"] == result.evidence_digest
    assert payload["claim_scope"] == "SOFTWARE_BENCHMARK_ONLY"
    assert payload["physical_execution_authorized"] is False
