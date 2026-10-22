export interface ConsistencyView {
  status: string
  detail: string
}

export function consistencyForScene(condition: string, stale: boolean): ConsistencyView {
  if (stale || condition === "stale_feed") {
    return { status: "STALE", detail: "The frame is too old to compare. No risk score is produced." }
  }
  if (condition === "occlusion_and_noise") {
    return {
      status: "CONFLICT",
      detail: "Camera and depth disagree by more than 0.50 m. The readings are not averaged.",
    }
  }
  if (condition === "human_in_cell") {
    return { status: "CONSISTENT", detail: "Two synthetic sources agree on the person. Agreement is not a clearance." }
  }
  return { status: "CONSISTENT", detail: "Two synthetic sources agree within 0.10 m. This is not a calibrated covariance test." }
}

export function fusionForScene(condition: string, stale: boolean): { status: string; detail: string } {
  if (stale || condition === "stale_feed") {
    return { status: "NOT_FUSED", detail: "A stale frame is not fused." }
  }
  if (condition === "occlusion_and_noise") {
    return { status: "CONFLICT_NOT_FUSED", detail: "Conflicting camera and depth readings are not averaged." }
  }
  return { status: "FUSED", detail: "Agreeing sources produce an INFERRED position, not an observation." }
}
