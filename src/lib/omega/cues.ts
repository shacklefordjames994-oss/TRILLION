export interface OperatorCue {
  cueType: string
  severity: "INFO" | "WARNING" | "CRITICAL"
  evidenceClass: "SIMULATED"
  title: string
  message: string
}

export function cuesForScene(latched: boolean, condition: string, stale: boolean): OperatorCue[] {
  const cues: OperatorCue[] = []
  if (stale || condition === "stale_feed") {
    cues.push({
      cueType: "FEED_STALE",
      severity: "WARNING",
      evidenceClass: "SIMULATED",
      title: "Feed stale",
      message: "No object conclusion is drawn from this frame.",
    })
  } else if (condition === "occlusion_and_noise") {
    cues.push({
      cueType: "PATH_UNCERTAIN",
      severity: "WARNING",
      evidenceClass: "SIMULATED",
      title: "Path uncertain",
      message: "The route crosses a region with no localized objects.",
    })
  } else if (condition === "human_in_cell") {
    cues.push({
      cueType: "PROXIMITY_WARNING",
      severity: "CRITICAL",
      evidenceClass: "SIMULATED",
      title: "Proximity warning",
      message: "A simulated person is inside the keep-out zone. This is not a certified detector.",
    })
  } else {
    cues.push({
      cueType: "OBJECT_DETECTED",
      severity: "INFO",
      evidenceClass: "SIMULATED",
      title: "Object hypothesis",
      message: "Synthetic container confidence 0.91. Evidence class remains SIMULATED.",
    })
  }
  if (latched || condition === "human_in_cell") {
    cues.push({
      cueType: "INHIBIT_ACTIVE",
      severity: "CRITICAL",
      evidenceClass: "SIMULATED",
      title: "Response inhibited",
      message: "This panel cannot clear the inhibit or approve motion.",
    })
  }
  return cues
}
