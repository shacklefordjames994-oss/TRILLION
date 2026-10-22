export type EvidenceClass = "OBSERVED" | "INFERRED" | "SIMULATED" | "UNKNOWN"
export type FeedStatus = "LIVE" | "STALE" | "DISCONNECTED" | "INVALID"
export type AuthorityState = "LATCHED" | "CLEAR" | "INDETERMINATE"

export interface BrainObject {
  objectId: string
  label: string
  evidenceClass: EvidenceClass
  confidence: number | null
  positionM: [number, number, number] | null
}

export interface BrainView {
  snapshotId: string
  authorityState: AuthorityState
  authorityRevision: number
  accepted: boolean
  issues: string[]
  feedStatus: FeedStatus
  poseEvidenceClass: EvidenceClass
  poseM: [number, number, number] | null
  objects: BrainObject[]
  unknownRegionCount: number
  task: string
  proposedAction: string
  riskFlags: string[]
  journal: string
  physicalExecutionEnabled: false
}

export function inspectBrain(latched: boolean, stale: boolean): BrainView {
  const issues: string[] = []
  if (latched) issues.push("AUTHORITY_INHIBIT_LATCHED")
  if (stale) issues.push("SNAPSHOT_STALE")
  return {
    snapshotId: "brain-sim-001",
    authorityState: latched ? "LATCHED" : "CLEAR",
    authorityRevision: latched ? 1 : 2,
    accepted: issues.length === 0,
    issues,
    feedStatus: stale ? "STALE" : "LIVE",
    poseEvidenceClass: "SIMULATED",
    poseM: stale ? null : [1.2, 0.4, 0],
    objects: stale
      ? []
      : [
          {
            objectId: "box-001",
            label: "red container",
            evidenceClass: "SIMULATED",
            confidence: 0.91,
            positionM: [-0.36, 0.09, 2.5],
          },
          {
            objectId: "shelf-mark",
            label: "marked shelf",
            evidenceClass: "INFERRED",
            confidence: 0.62,
            positionM: [0.9, 1.4, 0],
          },
          {
            objectId: "gap-7",
            label: "unresolved region",
            evidenceClass: "UNKNOWN",
            confidence: null,
            positionM: null,
          },
        ],
    unknownRegionCount: stale ? 2 : 1,
    task: "pick-place",
    proposedAction: stale
      ? "No action. The simulated feed is stale."
      : "Move the simulated container to the marked shelf.",
    riskFlags: stale ? ["STALE_FEED", "SIMULATION_ONLY"] : ["SIMULATION_ONLY", "UNKNOWN_REGION"],
    journal: latched ? "INHIBIT_LATCHED" : stale ? "PERCEPTION_REJECTED" : "RECORDED_NOT_EXECUTED",
    physicalExecutionEnabled: false,
  }
}

export interface WorldCondition {
  name: string
  title: string
  decision: string
  detail: string
  evidenceClass: "SIMULATED"
  physicalExecutionAuthorized: false
}

export const realWorldConditions: WorldCondition[] = [
  {
    name: "nominal_pick",
    title: "Clear aisle",
    decision: "SIMULATION_RECORDED",
    detail: "Two synthetic objects matched. Mean error 0.013 m. Not a physical measurement.",
    evidenceClass: "SIMULATED",
    physicalExecutionAuthorized: false,
  },
  {
    name: "human_in_cell",
    title: "Person in the cell",
    decision: "KEEP_OUT_INHIBIT",
    detail: "A simulated person entered the keep-out zone. The pick is refused.",
    evidenceClass: "SIMULATED",
    physicalExecutionAuthorized: false,
  },
  {
    name: "occlusion_and_noise",
    title: "Occlusion and depth noise",
    decision: "SIMULATION_DEGRADED",
    detail: "Both objects missed. Positions were not invented.",
    evidenceClass: "SIMULATED",
    physicalExecutionAuthorized: false,
  },
  {
    name: "stale_feed",
    title: "Stale feed",
    decision: "PERCEPTION_REJECTED",
    detail: "The frame is older than the allowed age. No action is taken.",
    evidenceClass: "SIMULATED",
    physicalExecutionAuthorized: false,
  },
]