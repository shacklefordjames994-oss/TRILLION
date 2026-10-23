import { useEffect, useRef, useState } from "react"
import { inspectBrain, realWorldConditions, type EvidenceClass } from "@/lib/omega/brain"
import { gradeScene } from "@/lib/omega/adaptive"
import { consistencyForScene, fusionForScene } from "@/lib/omega/consistency"
import { cuesForScene } from "@/lib/omega/cues"
import { requestPhysicalExecution } from "@/lib/omega/physical-inhibit"
import { demonstrateDecision } from "@/lib/omega/simulation-decision"
import { replayItems } from "@/lib/omega/timeline"

export function BrainConsole({ latched }: { latched: boolean }) {
  const [stale, setStale] = useState(false)
  const [condition, setCondition] = useState(realWorldConditions[0].name)
  const view = inspectBrain(latched, stale || condition === "stale_feed")
  const untrusted = !view.accepted || condition !== "nominal_pick"
  const selected = realWorldConditions.find((item) => item.name === condition) ?? realWorldConditions[0]
  const [selectedEvent, setSelectedEvent] = useState(replayItems[0].id)
  const [physicalDenial, setPhysicalDenial] = useState<string | null>(null)
  const [decisionCode, setDecisionCode] = useState<string | null>(null)
  const [usedDecision, setUsedDecision] = useState(false)
  const sensors = consistencyForScene(condition, stale || condition === "stale_feed")
  const fusion = fusionForScene(condition, stale || condition === "stale_feed")
  const grade = gradeScene(latched, condition, stale || condition === "stale_feed")
  const cues = cuesForScene(latched, condition, stale || condition === "stale_feed")
  const replay = replayItems.find((item) => item.id === selectedEvent) ?? replayItems[0]
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const context = canvas.getContext("2d")
    if (!context) return
    const width = canvas.width
    const height = canvas.height
    context.clearRect(0, 0, width, height)
    context.fillStyle = "#15191d"
    context.fillRect(0, 0, width, height)
    context.strokeStyle = "#3c4650"
    context.strokeRect(18, 18, width - 36, height - 36)
    context.fillStyle = "#d7dde3"
    context.font = "12px sans-serif"
    if (condition === "human_in_cell") {
      context.fillStyle = "#8f2d2d"
      context.fillRect(40, 40, 70, 110)
      context.fillStyle = "#d7dde3"
      context.fillText("SIMULATED person — keep out", 120, 70)
    } else if (condition === "occlusion_and_noise") {
      context.fillStyle = "#2a3036"
      context.fillRect(70, 50, 180, 90)
      context.fillStyle = "#d7dde3"
      context.fillText("Occluded — pose withheld", 78, 160)
    } else if (condition === "stale_feed") {
      context.fillStyle = "#8b939c"
      context.fillText("STALE simulated frame — rejected", 24, 90)
    } else {
      drawMark(context, 90, 120, "#3d8bfd", "SIMULATED container")
      drawMark(context, 200, 70, "#d4a017", "INFERRED shelf")
      context.fillStyle = "#d7dde3"
      context.fillText("SIMULATED pose", 24, height - 16)
    }
  }, [condition])

  return (
    <section className="panel" aria-live="polite">
      <div className="split-head">
        <h2>Optimus Brain</h2>
        <p className={untrusted ? "note held" : "note ok"}>{untrusted ? selected.decision : "Snapshot accepted"}</p>
      </div>
      <p className="note">
        Snapshot {view.snapshotId}. Authority {view.authorityState}, revision {view.authorityRevision}. Physical
        execution {view.physicalExecutionEnabled ? "enabled" : "disabled"}. A simulated view is not an observation.
      </p>
      {view.issues.length > 0 ? <p className="note">{view.issues.join(" · ")}</p> : null}
      <p className={sensors.status === "CONSISTENT" ? "note ok" : "note held"}>
        Sensors {sensors.status}. {sensors.detail} Fusion {fusion.status}. {fusion.detail} Physical execution stays
        inhibited.
      </p>
      <p className="note">
        Scenario suite: 1 of 1 injected conflicts caught, 0 missed, 1 of 1 stale frames rejected, 0 fail-closed
        violations. Denominator is 3 synthetic cases, not a field trial. A stored PASS still does not authorize motion.
        A reviewer cannot turn a failed run into a pass. The policy digest is recomputed from the trusted policy, and a
        mismatch does not clear the inhibit. A verified boot chain starts simulation only. It does not enable motion.
        A stored benchmark assessment does not clear the inhibit. The gate recomputes the result and does not trust a
        stored PASS.
      </p>
      <p className={grade.blocked ? "note held" : "note ok"}>
        {grade.grade} · risk {grade.risk}. {grade.reason} Proposal {grade.blocked ? "blocked" : "visible"}. Motion
        stays unauthorized. A brief safer reading does not lower a held grade, and a critical grade does not clear
        itself.
      </p>
      <h3>Hardware interlock</h3>
      <ul>
        <li className="contact is-open">
          <strong>E-stop loop</strong>
          <span>Open</span>
        </li>
        <li className="contact is-open">
          <strong>Watchdog</strong>
          <span>Open</span>
        </li>
        <li className="contact is-shut">
          <strong>Guard</strong>
          <span>Closed</span>
        </li>
        <li className="contact is-open">
          <strong>Actuator output</strong>
          <span>Disabled</span>
        </li>
      </ul>
      <p className="note held">
        Hardware model only. A closed chain in this view is not a safety certificate, and actuator output stays
        disabled. {physicalDenial ?? "Physical execution is inhibited. Approving a simulation does not release it."}
      </p>
      <div className="actions">
        <button type="button" className="ghost" onClick={() => setPhysicalDenial(requestPhysicalExecution().code)}>
          Request physical execution
        </button>
      </div>
      <ul>
        {cues.map((cue) => (
          <li key={cue.cueType}>
            <strong>{cue.severity}</strong> {cue.cueType} · {cue.evidenceClass}. {cue.message}
          </li>
        ))}
      </ul>
      <div className="desk-grid">
        <article>
          <h3>Sensor views</h3>
          <p className="note">
            Feed {view.feedStatus}. No camera image is attached. Depth and detections in this panel are {view.poseEvidenceClass}.
          </p>
        </article>
        <article>
          <h3>3D world</h3>
          <canvas ref={canvasRef} className="viewport" width={320} height={180} />
          <p className="note">
            Pose {view.poseEvidenceClass}
            {view.poseM ? ` (${view.poseM.join(", ")}) m` : " missing"}. Unknown regions: {view.unknownRegionCount}.
          </p>
        </article>
        <article>
          <h3>Plan inspection</h3>
          <p className="note">
            {view.task}: {view.proposedAction} Risks: {view.riskFlags.join(", ")}.
          </p>
        </article>
        <article>
          <h3>Swarm state</h3>
          <p className="note">sim-robot-01 · feed {view.feedStatus} · lease not granted by this view.</p>
        </article>
        <article>
          <h3>Event journal</h3>
          <p className="note">{view.journal}. Recovery does not execute this task.</p>
        </article>
        <article>
          <h3>Human authority</h3>
          <p className="note">Inhibit {view.authorityState}. This console cannot clear it or approve motion.</p>
        </article>
      </div>
      <ul>
        {view.objects.map((object) => (
          <li key={object.objectId}>
            <ClassMark value={object.evidenceClass} /> {object.label}
            {object.confidence === null ? " · confidence unknown" : ` · ${object.confidence.toFixed(2)}`}
            {object.positionM ? ` · ${object.positionM.join(", ")} m` : " · position withheld"}
          </li>
        ))}
      </ul>
      <h3>Evidence timeline</h3>
      <p className="note">Replay only. Selecting an event does not resume a task or move a robot.</p>
      <div className="actions">
        {replayItems.map((item) => (
          <button
            key={item.id}
            type="button"
            className={item.id === selectedEvent ? undefined : "ghost"}
            onClick={() => setSelectedEvent(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <p className="note">
        {replay.evidenceClass ? `${replay.evidenceClass} · ` : ""}
        {replay.detail}
      </p>
      <div className="actions">
        {realWorldConditions.map((item) => (
          <button
            key={item.name}
            type="button"
            className={item.name === condition ? undefined : "ghost"}
            onClick={() => setCondition(item.name)}
          >
            {item.title}
          </button>
        ))}
        <button type="button" className="ghost" onClick={() => setStale(false)}>
          Fresh simulation
        </button>
        <button type="button" className="ghost" onClick={() => setStale(true)}>
          Stale feed
        </button>
      </div>
      <p className="note">
        {selected.evidenceClass} · {selected.decision}. {selected.detail} Physical execution stays unauthorized.
      </p>
      <p className="note">
        {decisionCode
          ? `${decisionCode}. The inhibit was not cleared. Physical execution remains unauthorized.`
          : "Approve and reject are demonstration records. Neither one resets the inhibit."}
      </p>
      <div className="actions">
        <button
          type="button"
          onClick={() => {
            const decision = demonstrateDecision({
              latched,
              sceneInhibits: condition === "human_in_cell",
              actorId: "human-001",
              choice: "APPROVE",
              alreadyUsed: usedDecision,
            })
            setUsedDecision(true)
            setDecisionCode(decision.code)
          }}
        >
          Approve simulation
        </button>
        <button
          type="button"
          className="ghost"
          onClick={() => {
            const decision = demonstrateDecision({
              latched,
              sceneInhibits: condition === "human_in_cell",
              actorId: "human-001",
              choice: "REJECT",
              alreadyUsed: usedDecision,
            })
            setUsedDecision(true)
            setDecisionCode(decision.code)
          }}
        >
          Reject proposal
        </button>
        <button
          type="button"
          className="ghost"
          onClick={() =>
            setDecisionCode(
              demonstrateDecision({
                latched,
                sceneInhibits: condition === "human_in_cell",
                actorId: "robot-B",
                choice: "APPROVE",
                alreadyUsed: false,
              }).code,
            )
          }
        >
          Robot tries to approve
        </button>
      </div>
    </section>
  )
}

function ClassMark({ value }: { value: EvidenceClass }) {
  return <strong>{value}</strong>
}

function drawMark(context: CanvasRenderingContext2D, x: number, y: number, color: string, label: string) {
  context.fillStyle = color
  context.fillRect(x, y, 28, 28)
  context.fillStyle = "#d7dde3"
  context.font = "12px sans-serif"
  context.fillText(label, x + 34, y + 18)
}
