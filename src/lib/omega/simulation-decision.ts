const AUTHORIZED = new Set(["human-001"])

export function demonstrateDecision(input: {
  latched: boolean
  sceneInhibits: boolean
  actorId: string
  choice: "APPROVE" | "REJECT"
  alreadyUsed: boolean
}): { code: string; physicalExecutionPermitted: false; inhibitCleared: false } {
  const denied = { physicalExecutionPermitted: false as const, inhibitCleared: false as const }
  if (!AUTHORIZED.has(input.actorId)) return { code: "UNAUTHORIZED", ...denied }
  if (input.alreadyUsed) return { code: "REPLAYED_AUTHORIZATION", ...denied }
  if (input.choice === "REJECT") return { code: "SIMULATION_REJECTED", ...denied }
  if (input.latched || input.sceneInhibits) return { code: "BLOCKED", ...denied }
  return { code: "SIMULATION_ADMITTED", ...denied }
}
