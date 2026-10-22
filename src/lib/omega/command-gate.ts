export type GateCase = "startup" | "admit" | "replay" | "tamper" | "observed" | "stale" | "revoked" | "schema" | "execute"

const seen = new Set<string>()
let recorded = false
let executed = false

export interface GateView {
  code: string
  stage: string
  simulationPermitted: boolean
  adapterResult: string
  physicalExecutionAuthorized: false
}

export function resetCommandGate() {
  seen.clear()
  recorded = false
  executed = false
}

export function authorizeCommand(mode: GateCase, latched: boolean): GateView {
  const denied = (code: string, stage = "SECURITY_GATEWAY"): GateView => ({
    code,
    stage,
    simulationPermitted: false,
    adapterResult: "COMMAND_NOT_ADMITTED",
    physicalExecutionAuthorized: false,
  })

  if (mode === "schema") return denied("INVALID_OPERATION", "SCHEMA")
  if (mode === "execute") {
    if (latched) return denied("INHIBIT_LATCHED", "EXECUTION")
    if (!recorded) return denied("EVENT_NOT_RECORDED", "EXECUTION")
    if (executed) return denied("IDEMPOTENT_EXECUTION", "EXECUTION")
    executed = true
    return {
      code: "SIMULATION_EXECUTED",
      stage: "EXECUTION",
      simulationPermitted: true,
      adapterResult: "SIMULATION_EXECUTED",
      physicalExecutionAuthorized: false,
    }
  }
  if (latched || mode === "startup") return denied("INHIBIT_LATCHED")
  if (mode === "revoked") return denied("UNKNOWN_OR_REVOKED_KEY")
  if (mode === "tamper") return denied("SIGNATURE_INVALID")
  if (mode === "observed") return denied("NON_SIMULATED_EVIDENCE_BLOCKED")
  if (mode === "stale") return denied("STALE_OR_UNKNOWN_EPOCH")
  if (seen.has("command-1")) return denied("DUPLICATE_COMMAND")

  seen.add("command-1")
  recorded = true
  return {
    code: "SIMULATION_EVENT_RECORDED",
    stage: "SIMULATION_ADAPTER",
    simulationPermitted: true,
    adapterResult: "SIMULATION_EVENT_RECORDED",
    physicalExecutionAuthorized: false,
  }
}
