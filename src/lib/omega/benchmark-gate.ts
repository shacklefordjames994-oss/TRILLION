export type GateStatus = "PASS" | "FAIL" | "INDETERMINATE"

export interface GateView {
  status: GateStatus
  reasons: string[]
  digest: string
  physicalExecutionAuthorized: false
  claimScope: "SOFTWARE_BENCHMARK_ONLY"
}

interface Evidence {
  benchmark_id: string
  benchmark_version: string
  source: string
  created_at_ms: number
  seed: number
  test_count: number
  passed_tests: number
  failed_tests: number
  skipped_tests: number
  precision: number | null
  recall: number | null
  mean_localization_error_m: number | null
  max_localization_error_m: number | null
  physical_execution_enabled: boolean
  model_version: string
  evidence_digest: string
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("")
}

function canonical(evidence: Evidence): string {
  const payload: Record<string, unknown> = { ...evidence }
  delete payload.evidence_digest
  const keys = Object.keys(payload).sort()
  return `{${keys.map((key) => `${JSON.stringify(key)}:${JSON.stringify(payload[key])}`).join(",")}}`
}

function baseEvidence(): Evidence {
  return {
    benchmark_id: "warehouse-rgbd-v1",
    benchmark_version: "0.1",
    source: "SIMULATION_ONLY",
    created_at_ms: 100000,
    seed: 7,
    test_count: 10,
    passed_tests: 10,
    failed_tests: 0,
    skipped_tests: 0,
    precision: 0.99,
    recall: 0.98,
    mean_localization_error_m: 0.02,
    max_localization_error_m: 0.04,
    physical_execution_enabled: false,
    model_version: "synthetic-stub-0.1",
    evidence_digest: "",
  }
}

export type GateDemo = "valid" | "tamper" | "stale" | "missing" | "failed" | "ledger" | "physical"

export async function evaluateGateDemo(mode: GateDemo): Promise<GateView> {
  const evidence = baseEvidence()
  let maxAge = 300000
  let integrity: () => boolean = () => true

  if (mode === "tamper") evidence.recall = 0.5
  if (mode === "stale") maxAge = 500
  if (mode === "missing") evidence.precision = null
  if (mode === "failed") {
    evidence.passed_tests = 9
    evidence.failed_tests = 1
  }
  if (mode === "physical") evidence.physical_execution_enabled = true
  if (mode === "ledger") {
    integrity = () => {
      throw new Error("ledger unavailable")
    }
  }

  const calculated = await sha256Hex(canonical(evidence))
  if (mode !== "tamper") evidence.evidence_digest = calculated

  const failures: string[] = []
  const unknowns: string[] = []
  const now = 101000

  if (evidence.source !== "SIMULATION_ONLY") failures.push("SOURCE_NOT_SIMULATION_ONLY")
  if (evidence.physical_execution_enabled) failures.push("PHYSICAL_EXECUTION_FLAG_MUST_BE_FALSE")
  if (!evidence.benchmark_id || !evidence.benchmark_version) unknowns.push("BENCHMARK_IDENTITY_MISSING")
  if (!evidence.model_version) unknowns.push("MODEL_VERSION_MISSING")
  if (evidence.created_at_ms <= 0 || now < evidence.created_at_ms) unknowns.push("INVALID_OR_FUTURE_TIMESTAMP")
  else if (now - evidence.created_at_ms > maxAge) unknowns.push("EVIDENCE_STALE")

  const counts = [evidence.test_count, evidence.passed_tests, evidence.failed_tests, evidence.skipped_tests]
  if (counts.some((count) => !Number.isInteger(count) || count < 0)) failures.push("INVALID_TEST_COUNTS")
  else if (evidence.test_count !== evidence.passed_tests + evidence.failed_tests + evidence.skipped_tests) {
    failures.push("TEST_COUNTS_DO_NOT_RECONCILE")
  } else if (evidence.test_count < 1) unknowns.push("INSUFFICIENT_TEST_COVERAGE")

  if (evidence.failed_tests > 0) failures.push("TEST_FAILURES_PRESENT")
  if (evidence.skipped_tests > 0) unknowns.push("SKIPPED_TESTS_PRESENT")

  const metrics: [string, number | null, number, "min" | "max"][] = [
    ["precision", evidence.precision, 0.95, "min"],
    ["recall", evidence.recall, 0.95, "min"],
    ["mean_localization_error_m", evidence.mean_localization_error_m, 0.1, "max"],
    ["max_localization_error_m", evidence.max_localization_error_m, 0.25, "max"],
  ]
  for (const [name, value, threshold, bound] of metrics) {
    if (value === null || !Number.isFinite(value)) {
      unknowns.push(`METRIC_MISSING_OR_INVALID:${name}`)
      continue
    }
    if ((name === "precision" || name === "recall") && (value < 0 || value > 1)) {
      failures.push(`METRIC_OUT_OF_RANGE:${name}`)
      continue
    }
    if (bound === "min" && value < threshold) failures.push(`THRESHOLD_FAILED:${name}`)
    if (bound === "max" && value < 0) failures.push(`METRIC_OUT_OF_RANGE:${name}`)
    else if (bound === "max" && value > threshold) failures.push(`THRESHOLD_FAILED:${name}`)
  }

  if (!evidence.evidence_digest || evidence.evidence_digest !== calculated) failures.push("EVIDENCE_DIGEST_MISMATCH")
  try {
    if (integrity() !== true) unknowns.push("INTEGRITY_VERIFICATION_FAILED")
  } catch {
    unknowns.push("INTEGRITY_VERIFICATION_ERROR")
  }

  const status: GateStatus = failures.length > 0 ? "FAIL" : unknowns.length > 0 ? "INDETERMINATE" : "PASS"
  return {
    status,
    reasons: [...failures, ...unknowns],
    digest: calculated,
    physicalExecutionAuthorized: false,
    claimScope: "SOFTWARE_BENCHMARK_ONLY",
  }
}
