export interface TrustView {
  accepted: boolean
  reasons: string[]
  evidenceClass: "SIMULATED"
  retrieved: number
  physicalExecutionAuthorized: false
}

export type TrustCase = "valid" | "untrusted" | "tamper" | "stale" | "duplicate"

export function reviewExperience(published: Set<string>, mode: TrustCase): TrustView {
  const denied = (reasons: string[], retrieved = 0): TrustView => ({
    accepted: false,
    reasons,
    evidenceClass: "SIMULATED",
    retrieved,
    physicalExecutionAuthorized: false,
  })

  if (mode === "untrusted") return denied(["UNTRUSTED_SOURCE_ID"])
  if (mode === "tamper") return denied(["DIGEST_MISMATCH"])
  if (mode === "stale") return denied(["STALE_EXPERIENCE"], 0)

  if (published.has("exp-0001")) return denied(["DUPLICATE_EXPERIENCE_ID"])
  published.add("exp-0001")
  return {
    accepted: true,
    reasons: [],
    evidenceClass: "SIMULATED",
    retrieved: mode === "duplicate" ? 0 : 1,
    physicalExecutionAuthorized: false,
  }
}
