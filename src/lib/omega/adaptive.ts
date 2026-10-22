export interface AdaptiveView {
  grade: string
  risk: string
  blocked: boolean
  reason: string
}

export function gradeScene(latched: boolean, condition: string, stale: boolean): AdaptiveView {
  if (stale || condition === "stale_feed") {
    return {
      grade: "G4_DATA_INVALID",
      risk: "withheld",
      blocked: true,
      reason: "The simulated feed is stale, so no risk score is invented.",
    }
  }
  if (latched) {
    return {
      grade: "G3_CRITICAL_INHIBIT",
      risk: "withheld",
      blocked: true,
      reason: "The inhibit overrides the score. This grade does not clear it.",
    }
  }
  if (condition === "human_in_cell") {
    return {
      grade: "G2_HUMAN_REVIEW",
      risk: "0.650",
      blocked: true,
      reason: "Adjusted distance is critical and the estimated contact time is short.",
    }
  }
  if (condition === "occlusion_and_noise") {
    return {
      grade: "G0_MONITOR",
      risk: "0.233",
      blocked: false,
      reason: "Unknown regions are recorded, but this weight set stays below caution.",
    }
  }
  return {
    grade: "G0_MONITOR",
    risk: "0.020",
    blocked: false,
    reason: "Far, slow, and high quality. Monitoring only.",
  }
}
