import { HardwareSafetyChain } from "@/lib/omega/hardware"
import { physicalExecutionPermitted } from "@/lib/omega/physical-inhibit"

export class HumanAuthorityRequired extends Error {
  constructor(message: string) {
    super(message)
    this.name = "HumanAuthorityRequired"
  }
}

export interface KillSwitchState {
  latched: boolean
  revision: number
  reason: string
  changedBy: string
  authorizationId: string
}

export interface KillSwitchEvent {
  revision: number
  action: "INHIBIT" | "RESET"
  actorId: string
  reason: string
  authorizationId: string
}

export class HumanAuthorityKillSwitch {
  private readonly authorized: Set<string>
  private readonly used = new Set<string>()
  private events: KillSwitchEvent[]
  private current: KillSwitchState

  constructor(authorizedHumans: string[]) {
    const humans = new Set(authorizedHumans.map((actor) => actor.trim()).filter((actor) => actor.length > 0))
    if (humans.size === 0) throw new Error("At least one authorized human is required.")
    this.authorized = humans
    this.current = {
      latched: true,
      revision: 1,
      reason: "Startup inhibit",
      changedBy: "SYSTEM",
      authorizationId: "BOOT",
    }
    this.events = [
      {
        revision: 1,
        action: "INHIBIT",
        actorId: "SYSTEM",
        reason: "Startup inhibit",
        authorizationId: "BOOT",
      },
    ]
  }

  get state(): KillSwitchState {
    return { ...this.current }
  }

  get auditEvents(): KillSwitchEvent[] {
    return this.events.map((event) => ({ ...event }))
  }

  engage(actorId: string, reason: string): KillSwitchState {
    if (!actorId.trim() || !reason.trim()) throw new Error("Actor and reason are required.")
    const revision = this.current.revision + 1
    this.current = {
      latched: true,
      revision,
      reason: reason.trim(),
      changedBy: actorId.trim(),
      authorizationId: "INHIBIT",
    }
    this.events.push({
      revision,
      action: "INHIBIT",
      actorId: actorId.trim(),
      reason: reason.trim(),
      authorizationId: "INHIBIT",
    })
    return this.state
  }

  reset(actorId: string, authorizationId: string, reason: string): KillSwitchState {
    if (!this.authorized.has(actorId)) throw new HumanAuthorityRequired("Actor is not an authorized human.")
    if (!authorizationId.trim()) throw new HumanAuthorityRequired("A unique authorization ID is required.")
    if (!reason.trim()) throw new HumanAuthorityRequired("A reset reason is required.")
    if (!this.current.latched) throw new Error("Latch is already clear.")
    const authId = authorizationId.trim()
    if (this.used.has(authId)) throw new HumanAuthorityRequired("Authorization ID has already been used.")
    this.used.add(authId)
    const revision = this.current.revision + 1
    this.current = {
      latched: false,
      revision,
      reason: reason.trim(),
      changedBy: actorId,
      authorizationId: authId,
    }
    this.events.push({
      revision,
      action: "RESET",
      actorId,
      reason: reason.trim(),
      authorizationId: authId,
    })
    return this.state
  }

  permitsSimulation(): boolean {
    return !this.current.latched
  }

  permitsPhysicalExecution(): boolean {
    return physicalExecutionPermitted()
  }
}

const CRITICAL = new Set([
  "SIGNATURE_INVALID",
  "POLICY_ROLLBACK_REJECTED",
  "AUDIT_INTEGRITY_FAILURE",
  "UNAUTHORIZED_POLICY_CHANGE",
  "SAFETY_STATE_UNAVAILABLE",
  "UNAPPROVED_PHYSICAL_COMMAND",
])

export interface Incident {
  incidentId: string
  robotId: string
  code: string
  severity: "CRITICAL" | "HIGH" | "WARNING"
  description: string
  evidenceDigest: string
  policyRevision: number
  status: string
  actions: string[]
}

export interface MemoryRow {
  id: string
  label: string
  status: string
}

export interface LedgerRow {
  actorId: string
  eventType: string
  reason: string
}

export interface DeskSnapshot {
  latch: KillSwitchState
  hardware: ReturnType<HardwareSafetyChain["evaluate"]>
  audit: KillSwitchEvent[]
  incidents: Incident[]
  memories: MemoryRow[]
  retrieved: string[]
  ledger: LedgerRow[]
  task: string
  physical: false
}

export interface IncidentReport {
  robotId: string
  code: string
  description: string
  evidence: unknown
  policyRevision: number
  memoryRecordId?: string
}

async function sha256Hex(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value)
  const digest = await crypto.subtle.digest("SHA-256", bytes)
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("")
}

function canonicalEvidence(evidence: unknown): string {
  if (evidence && typeof evidence === "object" && "circular" in evidence && (evidence as { circular?: boolean }).circular) {
    throw new Error("Evidence could not be serialized")
  }
  return JSON.stringify(evidence, Object.keys((evidence as object) ?? {}).sort())
}

export class IncidentDesk {
  readonly killSwitch = new HumanAuthorityKillSwitch(["human-001"])
  readonly hardware = new HardwareSafetyChain(["human-001"])
  nowMs = 0
  private readonly reviewers = new Set(["human-001"])
  private readonly reviewIds = new Set<string>()
  private readonly quarantined = new Set<string>()
  private incidents: Incident[] = []
  private ledger: LedgerRow[] = []
  private sequence = 0
  private task = "No task is queued. A reset will not create one."
  memories: MemoryRow[] = [
    { id: "experience-123", label: "Grasp of the red container", status: "VALIDATED" },
    { id: "experience-keep", label: "Shelf placement, same cell", status: "VALIDATED" },
  ]
  failQuarantineWrite = false

  snapshot(): DeskSnapshot {
    const clear = this.killSwitch.permitsSimulation()
    return {
      latch: this.killSwitch.state,
      hardware: this.hardware.evaluate(this.nowMs),
      audit: this.killSwitch.auditEvents,
      incidents: this.incidents.map((incident) => ({ ...incident, actions: [...incident.actions] })),
      memories: this.memories.map((row) => ({ ...row })),
      retrieved: clear
        ? this.memories.filter((row) => row.status === "VALIDATED" && !this.quarantined.has(row.id)).map((row) => row.id)
        : [],
      ledger: this.ledger.map((row) => ({ ...row })),
      task: this.task,
      physical: false,
    }
  }

  private quarantine(memoryRecordId: string, incidentId: string): boolean {
    if (this.failQuarantineWrite) return false
    const row = this.memories.find((item) => item.id === memoryRecordId)
    if (!row) return false
    row.status = "QUARANTINED"
    this.quarantined.add(memoryRecordId)
    this.ledger.push({
      actorId: "SYSTEM",
      eventType: "MEMORY_QUARANTINED",
      reason: `incident=${incidentId}; memory=${memoryRecordId}`,
    })
    return true
  }

  async report(input: IncidentReport): Promise<Incident> {
    const robotId = input.robotId.trim() || "UNKNOWN"
    const code = input.code.trim() || "UNCLASSIFIED_FAILURE"
    const description = input.description.trim() || "No description supplied."
    const policyRevision = input.policyRevision
    const actions: string[] = []
    const incidentId = `incident-${++this.sequence}`

    if (CRITICAL.has(code) || code === "UNAPPROVED_BEHAVIOR") {
      this.killSwitch.engage(robotId, code)
      actions.push("INHIBIT_REQUESTED")
      try {
        this.hardware.demandStop(robotId, code)
        actions.push("HARDWARE_STOP_DEMANDED")
      } catch {
        actions.push("HARDWARE_STOP_FAILED")
      }
    }

    let evidenceDigest = "UNAVAILABLE"
    try {
      evidenceDigest = await sha256Hex(canonicalEvidence(input.evidence))
    } catch {
      actions.push("EVIDENCE_DIGEST_FAILED")
    }

    let status = "OPEN"
    if (input.memoryRecordId) {
      const quarantined = this.quarantine(input.memoryRecordId, incidentId)
      if (quarantined) actions.push("MEMORY_QUARANTINED")
      else {
        status = "QUARANTINE_FAILED"
        actions.push("QUARANTINE_FAILED")
      }
    }

    const incident: Incident = {
      incidentId,
      robotId,
      code,
      severity: CRITICAL.has(code) ? "CRITICAL" : "HIGH",
      description,
      evidenceDigest,
      policyRevision,
      status,
      actions,
    }
    this.incidents = [incident, ...this.incidents]
    this.ledger.push({
      actorId: robotId,
      eventType: `INCIDENT_${incident.severity}`,
      reason: `id=${incidentId}; code=${code}; evidence_digest=${evidenceDigest}`,
    })
    return incident
  }

  approveReview(incidentId: string, reviewerId: string, reviewId: string, disposition: string): void {
    if (!this.reviewers.has(reviewerId)) throw new Error("Reviewer is not authorized.")
    if (!reviewId.trim() || !disposition.trim()) throw new Error("Review ID and disposition are required.")
    if (!this.incidents.some((incident) => incident.incidentId === incidentId)) throw new Error("Unknown incident.")
    if (this.reviewIds.has(reviewId.trim())) throw new Error("Review ID has already been used.")
    this.reviewIds.add(reviewId.trim())
    this.ledger.push({
      actorId: reviewerId,
      eventType: "INCIDENT_HUMAN_REVIEW",
      reason: `incident=${incidentId}; review_id=${reviewId.trim()}; disposition=${disposition.trim()}`,
    })
  }

  submitStep(): string {
    if (!this.killSwitch.permitsSimulation()) {
      this.task = "Step refused. The swarm is inhibited."
      return this.task
    }
    this.task = "Simulation step accepted for evaluation only. No actuator command was issued."
    return this.task
  }
}

export async function runDeskChecks(): Promise<{ name: string; pass: boolean; detail: string }[]> {
  const checks: { name: string; pass: boolean; detail: string }[] = []
  function add(name: string, pass: boolean, detail: string) {
    checks.push({ name, pass, detail })
  }

  const desk = new IncidentDesk()
  add("Startup inhibit", desk.killSwitch.state.latched, "The desk starts latched.")
  add("Physical inhibit", desk.killSwitch.permitsPhysicalExecution() === false, "Reset cannot enable an actuator.")

  const critical = await desk.report({
    robotId: "robot-007",
    code: "SIGNATURE_INVALID",
    description: "Policy signature verification failed",
    evidence: { policy_id: "policy-demo" },
    policyRevision: 4,
  })
  add("Critical report inhibits", desk.killSwitch.state.latched && critical.actions.includes("INHIBIT_REQUESTED"), critical.incidentId)

  const memory = new IncidentDesk()
  await memory.report({
    robotId: "robot-007",
    code: "UNAPPROVED_BEHAVIOR",
    description: "Unapproved grasp",
    evidence: { action: "unknown_action" },
    policyRevision: 4,
    memoryRecordId: "experience-123",
  })
  const quarantined = memory.snapshot().memories.find((row) => row.id === "experience-123")
  add("Quarantine", quarantined?.status === "QUARANTINED" && !memory.snapshot().retrieved.includes("experience-123"), "Shared grasp memory is withheld.")

  const reviewDesk = new IncidentDesk()
  const incident = await reviewDesk.report({
    robotId: "robot-007",
    code: "SIGNATURE_INVALID",
    description: "Needs a human",
    evidence: { policy_id: "policy-demo" },
    policyRevision: 4,
  })
  let agentRejected = false
  try {
    reviewDesk.approveReview(incident.incidentId, "agent-001", "review-agent", "reject")
  } catch {
    agentRejected = true
  }
  reviewDesk.approveReview(incident.incidentId, "human-001", "review-001", "investigated")
  add(
    "Human review",
    agentRejected && reviewDesk.killSwitch.state.latched && reviewDesk.killSwitch.permitsPhysicalExecution() === false,
    "A review record does not clear the latch or permit motion.",
  )

  const switched = new IncidentDesk()
  let robotResetRejected = false
  try {
    switched.killSwitch.reset("robot-007", "approval-robot", "A robot cannot reset")
  } catch {
    robotResetRejected = true
  }
  switched.killSwitch.reset("human-001", "approval-check", "Check setup")
  add(
    "Authorized reset",
    robotResetRejected && switched.killSwitch.permitsSimulation() && switched.killSwitch.permitsPhysicalExecution() === false,
    "Simulation may be reassessed. Physical execution stays inhibited.",
  )

  const hardware = new IncidentDesk()
  let robotHardwareRejected = false
  try {
    hardware.hardware.hardwareReset("robot-007", "channel-robot", "attempt", hardware.nowMs)
  } catch {
    robotHardwareRejected = true
  }
  add("Actuator request", robotHardwareRejected && hardware.hardware.actuatorCommand().allowed === false, hardware.hardware.actuatorCommand().code)

  return checks
}
