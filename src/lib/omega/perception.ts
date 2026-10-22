export interface PerceivedObject {
  objectId: string
  className: string
  position: [number, number, number]
  confidence: number
  visible: boolean
  provenance: string
}

export interface PerceptionResult {
  accepted: boolean
  code: string
  frameId: string
  robotId: string
  source: string
  observedAtMs: number
  objects: PerceivedObject[]
  reason: string
}

export interface SpatialRelation {
  subjectId: string
  relation: string
  targetId: string
  distanceM: number | null
  confidence: number
  provenance: string
}

export interface VirtualObjectInput {
  objectId: string
  className: string
  position: [number, number, number]
  confidence: number
  visible?: boolean
}

export interface VirtualFrameInput {
  frameId: string
  robotId: string
  sceneId: string
  timestampMs: number
  coordinateFrame: string
  source: string
  objects: VirtualObjectInput[]
}

const SOURCES = new Set(["SIMULATED_RENDER", "SIMULATED_SCENE_GRAPH"])

function reject(
  frame: VirtualFrameInput,
  nowMs: number,
  code: string,
  reason: string,
): PerceptionResult {
  return {
    accepted: false,
    code,
    frameId: frame.frameId || "UNKNOWN",
    robotId: frame.robotId || "UNKNOWN",
    source: frame.source || "UNKNOWN",
    observedAtMs: nowMs,
    objects: [],
    reason,
  }
}

export function perceiveFrame(
  frame: VirtualFrameInput,
  nowMs: number,
  allowedRobots = ["robot-001"],
  allowedScenes = ["warehouse-sim-v1"],
  maxAgeMs = 1000,
): PerceptionResult {
  if (!allowedRobots.includes(frame.robotId)) {
    return reject(frame, nowMs, "ROBOT_NOT_ALLOWED", "Robot is not allowlisted.")
  }
  if (!allowedScenes.includes(frame.sceneId)) {
    return reject(frame, nowMs, "SCENE_NOT_ALLOWED", "Scene is not allowlisted.")
  }
  if (!SOURCES.has(frame.source)) {
    return reject(frame, nowMs, "SOURCE_NOT_ALLOWED", "Source is not a virtual source.")
  }
  if (frame.coordinateFrame !== "world") {
    return reject(frame, nowMs, "COORDINATE_FRAME_UNSUPPORTED", "This adapter requires the world coordinate frame.")
  }
  if (frame.timestampMs > nowMs) {
    return reject(frame, nowMs, "FUTURE_FRAME", "Frame timestamp is in the future.")
  }
  if (nowMs - frame.timestampMs > maxAgeMs) {
    return reject(frame, nowMs, "STALE_FRAME", "Frame exceeds maximum permitted age.")
  }
  if (!frame.frameId || frame.objects.length === 0) {
    return reject(frame, nowMs, "INVALID_FRAME", "Frame ID or object list is missing.")
  }

  const seen = new Set<string>()
  const objects: PerceivedObject[] = []
  for (const obj of frame.objects) {
    if (!obj.objectId || !obj.className) {
      return reject(frame, nowMs, "INVALID_OBJECT", "Object ID/class is missing.")
    }
    if (seen.has(obj.objectId)) {
      return reject(frame, nowMs, "DUPLICATE_OBJECT_ID", "Object IDs must be unique.")
    }
    seen.add(obj.objectId)
    if (obj.position.length !== 3 || obj.position.some((value) => !Number.isFinite(value))) {
      return reject(frame, nowMs, "INVALID_POSITION", "Position must contain finite numeric coordinates.")
    }
    if (!Number.isFinite(obj.confidence) || obj.confidence < 0 || obj.confidence > 1) {
      return reject(frame, nowMs, "INVALID_CONFIDENCE", "Confidence must be in [0, 1].")
    }
    objects.push({
      objectId: obj.objectId,
      className: obj.className,
      position: [obj.position[0], obj.position[1], obj.position[2]],
      confidence: obj.confidence,
      visible: obj.visible !== false,
      provenance: frame.source,
    })
  }

  return {
    accepted: true,
    code: "VIRTUAL_PERCEPTION_ACCEPTED",
    frameId: frame.frameId,
    robotId: frame.robotId,
    source: frame.source,
    observedAtMs: frame.timestampMs,
    objects,
    reason: "Validated virtual scene data; not a physical observation.",
  }
}

export function deriveSpatialRelations(
  result: PerceptionResult,
  nearThresholdM = 1,
  minimumConfidence = 0.5,
): SpatialRelation[] {
  if (!result.accepted) return []
  const objects = result.objects.filter((obj) => obj.visible && obj.confidence >= minimumConfidence)
  const relations: SpatialRelation[] = []
  for (let i = 0; i < objects.length; i += 1) {
    for (let j = i + 1; j < objects.length; j += 1) {
      const a = objects[i]
      const b = objects[j]
      const [ax, ay, az] = a.position
      const [bx, by, bz] = b.position
      const distance = Math.hypot(ax - bx, ay - by, az - bz)
      const confidence = Math.min(a.confidence, b.confidence)
      relations.push({
        subjectId: a.objectId,
        relation: "DISTANCE_M",
        targetId: b.objectId,
        distanceM: distance,
        confidence,
        provenance: result.source,
      })
      if (distance <= nearThresholdM) {
        relations.push({
          subjectId: a.objectId,
          relation: "NEAR",
          targetId: b.objectId,
          distanceM: distance,
          confidence,
          provenance: result.source,
        })
      }
      if (ax < bx) {
        relations.push({
          subjectId: a.objectId,
          relation: "LEFT_OF",
          targetId: b.objectId,
          distanceM: null,
          confidence,
          provenance: result.source,
        })
      } else if (ax > bx) {
        relations.push({
          subjectId: a.objectId,
          relation: "RIGHT_OF",
          targetId: b.objectId,
          distanceM: null,
          confidence,
          provenance: result.source,
        })
      }
      if (ay < by) {
        relations.push({
          subjectId: a.objectId,
          relation: "BELOW",
          targetId: b.objectId,
          distanceM: null,
          confidence,
          provenance: result.source,
        })
      } else if (ay > by) {
        relations.push({
          subjectId: a.objectId,
          relation: "ABOVE",
          targetId: b.objectId,
          distanceM: null,
          confidence,
          provenance: result.source,
        })
      }
    }
  }
  return relations
}

export function authorizeVirtualPerception(
  result: PerceptionResult,
  latched: boolean,
  ledgerOk: boolean,
): { allowed: boolean; code: string } {
  if (!ledgerOk) return { allowed: false, code: "AUDIT_INTEGRITY_FAILURE" }
  if (latched) return { allowed: false, code: "KILL_SWITCH_LATCHED" }
  if (!result.accepted) return { allowed: false, code: "PERCEPTION_REJECTED" }
  if (!SOURCES.has(result.source)) return { allowed: false, code: "SOURCE_NOT_ALLOWED" }
  return { allowed: true, code: "SIMULATION_DATA_ONLY" }
}

export function warehouseFrame(robotId: string, timestampMs: number): VirtualFrameInput {
  return {
    frameId: "frame-001",
    robotId,
    sceneId: "warehouse-sim-v1",
    timestampMs,
    coordinateFrame: "world",
    source: "SIMULATED_SCENE_GRAPH",
    objects: [
      { objectId: "box-1", className: "box", position: [0, 0, 0], confidence: 0.98 },
      { objectId: "table-1", className: "table", position: [0.5, 0, 0], confidence: 0.95 },
    ],
  }
}
