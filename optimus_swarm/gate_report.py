from dataclasses import asdict
from enum import Enum
import json
from pathlib import Path

from optimus_swarm.benchmark_gate import GatePolicy, GateResult, evaluate_benchmark


def _json_safe(value):
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json_safe(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def write_gate_report(output_path: str, benchmark_id: str, result: GateResult) -> None:
    report = {
        "schema_version": "1.0",
        "benchmark_id": benchmark_id,
        "gate_status": result.status.value,
        "reasons": list(result.reasons),
        "evidence_digest": result.evidence_digest,
        "physical_execution_authorized": False,
        "claim_scope": "SOFTWARE_BENCHMARK_ONLY",
    }

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def review_benchmark(
    evidence,
    *,
    now_ms: int,
    integrity_verifier,
    output_path: str = "artifacts/benchmark-gate.json",
    policy: GatePolicy | None = None,
):
    """Reporting only. Never starts, resumes, or authorizes a robot."""
    result = evaluate_benchmark(
        evidence,
        policy or GatePolicy(),
        now_ms=now_ms,
        verify_integrity=integrity_verifier,
    )
    write_gate_report(
        output_path=output_path,
        benchmark_id=evidence.benchmark_id,
        result=result,
    )
    return result
