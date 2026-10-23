from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from optimus_swarm.kill_switch import HumanAuthorityKillSwitch
from optimus_swarm.safety_case import (
    BenchmarkEvidence,
    ReviewRecord,
    RunStatus,
    apply_review,
    canonical_json,
    digest,
    validate_benchmark,
)


@dataclass(frozen=True)
class TrustedPolicy:
    """Version-controlled policy. The digest is computed from this object, not from a run."""

    policy_version: str
    conflict_distance_m: float
    max_age_ms: int
    max_implied_speed_mps: float


@dataclass(frozen=True)
class IntegrityResult:
    status: RunStatus
    reasons: tuple[str, ...]
    recomputed_policy_digest: str
    inhibit_cleared: bool = False
    physical_execution_permitted: bool = False


def policy_digest(policy: TrustedPolicy) -> str:
    if not isinstance(policy.policy_version, str) or not policy.policy_version.strip():
        raise ValueError("policy_version is required")
    if not math.isfinite(policy.conflict_distance_m) or policy.conflict_distance_m <= 0:
        raise ValueError("invalid conflict distance")
    if isinstance(policy.max_age_ms, bool) or not isinstance(policy.max_age_ms, int) or policy.max_age_ms < 0:
        raise ValueError("invalid max age")
    if not math.isfinite(policy.max_implied_speed_mps) or policy.max_implied_speed_mps <= 0:
        raise ValueError("invalid implied speed")
    return digest(asdict(policy))


def _inhibit_unchanged(kill_switch: HumanAuthorityKillSwitch | None, revision: int | None, latched: bool | None) -> bool:
    if kill_switch is None:
        return True
    state = kill_switch.state
    return state.revision == revision and state.latched == latched and kill_switch.permits_physical_execution() is False


def verify_policy_integrity(
    run: BenchmarkEvidence,
    trusted: TrustedPolicy,
    *,
    kill_switch: HumanAuthorityKillSwitch | None = None,
    review: ReviewRecord | None = None,
) -> IntegrityResult:
    """Recompute the policy digest. This function does not reset the inhibit."""
    revision = None if kill_switch is None else kill_switch.state.revision
    latched = None if kill_switch is None else kill_switch.state.latched
    try:
        recomputed = policy_digest(trusted)
    except ValueError:
        return IntegrityResult(RunStatus.INDETERMINATE, ("Trusted policy invalid",), "", False, False)

    gate = validate_benchmark(run, run.required_scenario_ids, recomputed)
    gate = apply_review(gate, review)
    if not _inhibit_unchanged(kill_switch, revision, latched):
        return IntegrityResult(RunStatus.FAIL, gate.reasons + ("Inhibit changed during verification",), recomputed, True, False)
    return IntegrityResult(gate.status, gate.reasons, recomputed, False, False)


def verify_stored_package(
    path: str | Path,
    run_id: str,
    trusted: TrustedPolicy,
    *,
    kill_switch: HumanAuthorityKillSwitch | None = None,
) -> IntegrityResult:
    """Reload a package from SQLite and reject a payload that no longer matches its digest."""
    revision = None if kill_switch is None else kill_switch.state.revision
    latched = None if kill_switch is None else kill_switch.state.latched
    try:
        recomputed = policy_digest(trusted)
    except ValueError:
        return IntegrityResult(RunStatus.INDETERMINATE, ("Trusted policy invalid",), "", False, False)

    try:
        with sqlite3.connect(str(path), timeout=5.0) as db:
            row = db.execute(
                "SELECT package_digest, package_json FROM safety_cases WHERE run_id = ?",
                (run_id,),
            ).fetchone()
    except sqlite3.Error:
        return IntegrityResult(RunStatus.INDETERMINATE, ("Evidence journal unavailable",), recomputed, False, False)

    if row is None:
        return IntegrityResult(RunStatus.INDETERMINATE, ("Stored package missing",), recomputed, False, False)

    stored_digest, payload = row
    reasons: list[str] = []
    parsed: object
    try:
        parsed = json.loads(payload)
        body = parsed.get("package") if isinstance(parsed, dict) else None
        recomputed_package = digest(body) if isinstance(body, dict) else ""
    except (json.JSONDecodeError, TypeError, ValueError):
        parsed = None
        recomputed_package = ""
    if recomputed_package != stored_digest:
        reasons.append("Stored package digest mismatch")
    claimed = None
    if isinstance(parsed, dict):
        claimed = parsed.get("package", {}).get("run", {}).get("policy_digest")
        if parsed.get("package", {}).get("physical_execution_enabled") is not False:
            reasons.append("Physical execution must remain disabled")
    if claimed != recomputed:
        reasons.append("Policy digest mismatch")
    if not _inhibit_unchanged(kill_switch, revision, latched):
        reasons.append("Inhibit changed during verification")

    if reasons:
        failed = any(marker in reason for reason in reasons for marker in ("digest mismatch", "Physical execution"))
        status = RunStatus.FAIL if failed else RunStatus.INDETERMINATE
        return IntegrityResult(status, tuple(reasons), recomputed, False, False)
    return IntegrityResult(RunStatus.PASS, (), recomputed, False, False)


def package_bytes(package: dict) -> str:
    return canonical_json(package)
