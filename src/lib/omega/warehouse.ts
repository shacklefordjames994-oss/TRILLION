export interface BoxDetection {
  objectId: string
  className: string
  bbox: [number, number, number, number]
  color: string
  estimate: [number, number, number]
  truth: [number, number, number]
  errorM: number
  confidence: number
  depthSpreadM: number
}

export interface WarehouseView {
  accepted: boolean
  code: string
  width: number
  height: number
  boxes: BoxDetection[]
  matched: number
  groundTruth: number
  missed: number
  falsePositives: number
  meanErrorM: number | null
  maxErrorM: number | null
  gate: string
  exported: boolean
}

interface Target {
  objectId: string
  className: string
  position: [number, number, number]
  size: [number, number, number]
  color: string
}

const TARGETS: Target[] = [
  { objectId: "box-001", className: "box", position: [-0.35, 0.1, 2.5], size: [0.45, 0.4, 0.35], color: "#2896dc" },
  { objectId: "crate-002", className: "crate", position: [0.4, -0.05, 3.2], size: [0.55, 0.5, 0.5], color: "#d28c28" },
]

function trunc(value: number): number {
  return value < 0 ? Math.ceil(value) : Math.floor(value)
}

export function runWarehouseBenchmark(allowedRobot: boolean, latched: boolean): WarehouseView {
  const width = 320
  const height = 240
  const fx = 240
  const fy = 240
  const cx = width / 2
  const cy = height / 2

  if (!allowedRobot) {
    return {
      accepted: false,
      code: "ROBOT_NOT_ALLOWED",
      width,
      height,
      boxes: projectTargets(width, height, fx, fy, cx, cy),
      matched: 0,
      groundTruth: TARGETS.length,
      missed: TARGETS.length,
      falsePositives: 0,
      meanErrorM: null,
      maxErrorM: null,
      gate: "PERCEPTION_REJECTED",
      exported: false,
    }
  }

  const boxes = projectTargets(width, height, fx, fy, cx, cy)
  const errors = boxes.map((box) => box.errorM)
  const mean = errors.reduce((sum, error) => sum + error, 0) / errors.length
  return {
    accepted: true,
    code: "RGBD_PERCEPTION_ACCEPTED",
    width,
    height,
    boxes,
    matched: boxes.length,
    groundTruth: TARGETS.length,
    missed: 0,
    falsePositives: 0,
    meanErrorM: mean,
    maxErrorM: Math.max(...errors),
    gate: latched ? "KILL_SWITCH_LATCHED" : "SIMULATION_ONLY",
    exported: !latched,
  }
}

function projectTargets(
  width: number,
  height: number,
  fx: number,
  fy: number,
  cx: number,
  cy: number,
): BoxDetection[] {
  return TARGETS.map((target) => {
    const [x, y, z] = target.position
    const [sx, sy] = target.size
    const u = trunc((fx * x) / z + cx)
    const v = trunc((fy * y) / z + cy)
    const halfW = Math.max(2, trunc((fx * sx) / (2 * z)))
    const halfH = Math.max(2, trunc((fy * sy) / (2 * z)))
    const x1 = Math.max(0, u - halfW)
    const x2 = Math.min(width, u + halfW)
    const y1 = Math.max(0, v - halfH)
    const y2 = Math.min(height, v + halfH)
    const pixelU = (x1 + x2 - 1) / 2
    const pixelV = (y1 + y2 - 1) / 2
    const estimate: [number, number, number] = [((pixelU - cx) * z) / fx, ((pixelV - cy) * z) / fy, z]
    const errorM = Math.hypot(estimate[0] - x, estimate[1] - y, estimate[2] - z)
    return {
      objectId: target.objectId,
      className: target.className,
      bbox: [x1, y1, x2, y2],
      color: target.color,
      estimate,
      truth: target.position,
      errorM,
      confidence: 0.99,
      depthSpreadM: 0,
    }
  })
}

export function paintWarehouse(canvas: HTMLCanvasElement, view: WarehouseView) {
  const ctx = canvas.getContext("2d")
  if (!ctx) return
  const scale = 2
  canvas.width = view.width * scale
  canvas.height = view.height * scale
  ctx.setTransform(scale, 0, 0, scale, 0, 0)
  ctx.fillStyle = "#282d34"
  ctx.fillRect(0, 0, view.width, view.height)

  for (const box of view.boxes) {
    const [x1, y1, x2, y2] = box.bbox
    ctx.fillStyle = box.color
    ctx.fillRect(x1, y1, x2 - x1, y2 - y1)
    ctx.strokeStyle = "#f4efe4"
    ctx.lineWidth = 1.5
    ctx.strokeRect(x1 + 0.5, y1 + 0.5, x2 - x1 - 1, y2 - y1 - 1)
    const [x, y, z] = box.estimate
    ctx.fillStyle = "#f4efe4"
    ctx.font = "11px 'IBM Plex Mono', monospace"
    const label = view.accepted
      ? `${box.objectId}  ${x.toFixed(2)}, ${y.toFixed(2)}, ${z.toFixed(2)} m`
      : `${box.className}: not released`
    ctx.fillText(label, x1, Math.max(12, y1 - 6))
  }

  ctx.fillStyle = view.accepted ? "#d7e7c8" : "#ffb2a4"
  ctx.font = "12px 'IBM Plex Mono', monospace"
  ctx.fillText(view.accepted ? "SIMULATION ONLY" : `REJECTED ${view.code}`, 8, 16)
}
