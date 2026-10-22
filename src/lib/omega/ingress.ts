export interface IngressView {
  accepted: boolean
  reasons: string[]
  evidenceClass: "SIMULATED" | null
  physicalExecutionAuthorized: false
}

export class BrowserReplay {
  private seen = new Set<string>()
  private last = new Map<string, number>()

  reserve(messageId: string, sequence: number): { ok: boolean; reason: string } {
    if (this.seen.has(messageId)) return { ok: false, reason: "DUPLICATE_MESSAGE_ID" }
    const previous = this.last.get("robot-001|key-robot-001-v1") ?? 0
    if (sequence <= previous) return { ok: false, reason: "REPLAYED_OR_OUT_OF_ORDER_SEQUENCE" }
    this.seen.add(messageId)
    this.last.set("robot-001|key-robot-001-v1", sequence)
    return { ok: true, reason: "SEQUENCE_ACCEPTED" }
  }
}

export type IngressCase = "valid" | "replay" | "tamper" | "expired" | "revoked" | "sequence"

export function receiveDemo(guard: BrowserReplay, mode: IngressCase): IngressView {
  const denied = (reasons: string[]): IngressView => ({
    accepted: false,
    reasons,
    evidenceClass: null,
    physicalExecutionAuthorized: false,
  })

  if (mode === "tamper") return denied(["PAYLOAD_DIGEST_MISMATCH", "SIGNATURE_INVALID"])
  if (mode === "expired") return denied(["ENVELOPE_EXPIRED"])
  if (mode === "revoked") return denied(["KEY_REVOKED_OR_NOT_ACTIVE"])

  const messageId = mode === "sequence" ? "message-002" : "message-001"
  const sequence = mode === "sequence" ? 1 : 1
  const reserved = guard.reserve(messageId, sequence)
  if (!reserved.ok) return denied([reserved.reason])

  return {
    accepted: true,
    reasons: ["SIGNATURE_AND_REPLAY_CHECKS_PASSED"],
    evidenceClass: "SIMULATED",
    physicalExecutionAuthorized: false,
  }
}
