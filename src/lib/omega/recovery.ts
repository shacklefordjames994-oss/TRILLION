export type RecoveryCase = "clean" | "expired" | "two-owners" | "missing-beat"

export interface RecoveryView {
  status: "READY" | "INHIBITED" | "INDETERMINATE"
  issues: string[]
  decision: string
  mayContinue: boolean
  physicalExecutionAuthorized: false
}

export function reviewRecovery(mode: RecoveryCase, humanReview: boolean): RecoveryView {
  if (mode === "two-owners") {
    return {
      status: "INDETERMINATE",
      issues: ["MULTIPLE_TASK_OWNERS"],
      decision: "AUTHORITATIVE_STATE_UNCERTAIN",
      mayContinue: false,
      physicalExecutionAuthorized: false,
    }
  }
  if (mode === "expired") {
    return {
      status: "INHIBITED",
      issues: ["LEASE_EXPIRED"],
      decision: "RECOVERY_CHECKS_FAILED",
      mayContinue: false,
      physicalExecutionAuthorized: false,
    }
  }
  if (mode === "missing-beat") {
    return {
      status: "INHIBITED",
      issues: ["MISSING_HEARTBEAT"],
      decision: "RECOVERY_CHECKS_FAILED",
      mayContinue: false,
      physicalExecutionAuthorized: false,
    }
  }
  if (!humanReview) {
    return {
      status: "READY",
      issues: [],
      decision: "RECOVERY_REVIEW_NOT_RECORDED",
      mayContinue: false,
      physicalExecutionAuthorized: false,
    }
  }
  return {
    status: "READY",
    issues: [],
    decision: "SIMULATION_RECOVERY_APPROVED",
    mayContinue: true,
    physicalExecutionAuthorized: false,
  }
}

export function runSwarmRecovery(mode: RecoveryCase): RecoveryView {
  if (mode === "two-owners") {
    return {
      status: "INDETERMINATE",
      issues: ["MULTIPLE_TASK_OWNERS", "OWNERSHIP_NOT_REWRITTEN"],
      decision: "Inhibit latched. Conflicting leases were left unchanged.",
      mayContinue: false,
      physicalExecutionAuthorized: false,
    }
  }
  return {
    status: mode === "clean" ? "READY" : "INHIBITED",
    issues: mode === "clean" ? ["LEASES_FENCED_NOT_RESUMED"] : [mode === "expired" ? "LEASE_EXPIRED" : "MISSING_HEARTBEAT"],
    decision: "Inhibit latched. No task was resumed.",
    mayContinue: false,
    physicalExecutionAuthorized: false,
  }
}
