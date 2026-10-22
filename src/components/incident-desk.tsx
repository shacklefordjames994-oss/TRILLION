import { useEffect, useRef, useState } from "react"
import { BrainConsole } from "@/components/brain-console"
import { Ban, ShieldAlert } from "lucide-react"
import { authorizeCommand, resetCommandGate, type GateCase, type GateView } from "@/lib/omega/command-gate"
import { IncidentDesk, runDeskChecks, type DeskSnapshot } from "@/lib/omega/desk"
import type { ChainStatus } from "@/lib/omega/hardware"
import { reviewRecovery, runSwarmRecovery, type RecoveryCase } from "@/lib/omega/recovery"
import { faultSweep } from "@/lib/omega/sweep-results"
import { paintWarehouse, runWarehouseBenchmark } from "@/lib/omega/warehouse"

const BOOT_CHAIN: ChainStatus = {
  estopLoopClosed: false,
  watchdogClosed: false,
  guardClosed: true,
  feedbackAgrees: true,
  faultLatched: false,
  motionPower: false,
  actuatorOutputEnabled: false,
  reason: "ESTOP_OPEN",
}

const EMPTY: DeskSnapshot = {
  latch: {
    latched: true,
    revision: 1,
    reason: "Startup inhibit",
    changedBy: "SYSTEM",
    authorizationId: "BOOT",
  },
  hardware: BOOT_CHAIN,
  audit: [],
  incidents: [],
  memories: [],
  retrieved: [],
  ledger: [],
  task: "No task is queued. A reset will not create one.",
  physical: false,
}

export function IncidentDeskView() {
  const deskRef = useRef<IncidentDesk | null>(null)
  if (deskRef.current === null) deskRef.current = new IncidentDesk()
  const desk = deskRef.current

  const [snap, setSnap] = useState<DeskSnapshot>(EMPTY)
  const [banner, setBanner] = useState<string | null>(null)
  const [authId, setAuthId] = useState("")
  const [channelId, setChannelId] = useState("")
  const [reviewId, setReviewId] = useState("")
  const [checks, setChecks] = useState<{ name: string; pass: boolean; detail: string }[]>([])
  const [robotAllowed, setRobotAllowed] = useState(true)
  const [recoveryCase, setRecoveryCase] = useState<RecoveryCase>("clean")
  const [recoveryReviewed, setRecoveryReviewed] = useState(false)
  const [gateView, setGateView] = useState<GateView>({
    code: "INHIBIT_LATCHED",
    stage: "SECURITY_GATEWAY",
    simulationPermitted: false,
    adapterResult: "COMMAND_NOT_ADMITTED",
    physicalExecutionAuthorized: false,
  })
  const canvasRef = useRef<HTMLCanvasElement>(null)

  function refresh() {
    setSnap(desk.snapshot())
  }

  useEffect(() => {
    refresh()
    let cancel = false
    runDeskChecks().then((rows) => {
      if (!cancel) setChecks(rows)
    })
    return () => {
      cancel = true
    }
    // The desk is created once for this page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function run(action: () => Promise<unknown> | unknown) {
    setBanner(null)
    try {
      await action()
    } catch (error) {
      setBanner(error instanceof Error ? error.message : "Action rejected.")
    }
    refresh()
  }

  const latched = snap.latch.latched
  const latest = snap.incidents[0]
  const vision = runWarehouseBenchmark(robotAllowed, latched)

  useEffect(() => {
    if (canvasRef.current) paintWarehouse(canvasRef.current, vision)
  }, [vision])

  return (
    <main className="desk">
      <header className="desk-top">
        <div>
          <p className="eyebrow">Optimus Ω · simulation policy</p>
          <h1>Incident desk</h1>
          <p className="lede">
            The software latch and the hardware chain are separate. Clearing the latch does not
            restore motion power, and this page still cannot command an actuator.
          </p>
        </div>
        <p className="stamp">Not a certified stop</p>
      </header>

      <section className={latched ? "latch is-closed" : "latch is-open"} aria-live="polite">
        <ShieldAlert aria-hidden="true" />
        <div>
          <p className="latch-title">{latched ? "Swarm inhibited" : "Simulation latch clear"}</p>
          <p>
            Rev {snap.latch.revision} · {snap.latch.changedBy} · {snap.latch.reason}
          </p>
        </div>
        <p className="physical">
          <Ban aria-hidden="true" /> Physical execution disabled
        </p>
      </section>

      <BrainConsole latched={latched} />

      <RecoveryPanel
        mode={recoveryCase}
        reviewed={recoveryReviewed}
        onMode={setRecoveryCase}
        onReviewed={setRecoveryReviewed}
        onRun={() => {
          setGateView({
            code: "INHIBIT_LATCHED",
            stage: "SECURITY_GATEWAY",
            simulationPermitted: false,
            adapterResult: "COMMAND_NOT_ADMITTED",
            physicalExecutionAuthorized: false,
          })
        }}
      />

      <CommandPanel
        view={gateView}
        onChoose={(mode) => {
          if (mode === "admit") resetCommandGate()
          setGateView(authorizeCommand(mode, mode === "startup" ? true : latched))
        }}
      />

      <section className="panel chain-panel" aria-live="polite">
        <div className="split-head">
          <h2>Hardware chain</h2>
          <p className="note">{snap.hardware.reason}</p>
        </div>
        <ul className="chain">
          <Contact name="E-stop loop" closed={snap.hardware.estopLoopClosed} />
          <Contact name="Watchdog" closed={snap.hardware.watchdogClosed} />
          <Contact name="Guard" closed={snap.hardware.guardClosed} />
          <Contact
            name="Feedback"
            closed={snap.hardware.feedbackAgrees && !snap.hardware.faultLatched}
            shut="Agrees"
            open="Disagrees"
          />
          <Contact name="Motion power" closed={snap.hardware.motionPower} shut="On" open="Off" />
        </ul>
        <p className="note">
          Contacts are in series. One open contact removes power. A robot pulse does not refresh
          the watchdog. Actuator output from this program stays off even if the model chain closes.
        </p>
        <div className="actions">
          <button type="button" onClick={() => run(() => desk.hardware.demandStop("robot-007", "E-stop pressed"))}>
            Press E-stop
          </button>
          <button type="button" onClick={() => run(() => desk.hardware.releaseEstop("human-001"))}>
            Release E-stop
          </button>
          <button type="button" onClick={() => run(() => desk.hardware.pulse("safety-plc", desk.nowMs))}>
            Safety-PLC pulse
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() =>
              run(() => {
                const accepted = desk.hardware.pulse("robot-007", desk.nowMs)
                if (!accepted) throw new Error("Robot watchdog pulse ignored.")
              })
            }
          >
            Robot pulse
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() =>
              run(() => {
                desk.nowMs += 1000
              })
            }
          >
            Expire watchdog
          </button>
          <button type="button" className="ghost" onClick={() => run(() => desk.hardware.openGuard("Person in the cell"))}>
            Open guard
          </button>
          <button type="button" onClick={() => run(() => desk.hardware.closeGuard("human-001"))}>
            Close guard
          </button>
        </div>
        <label>
          Hardware channel id
          <input
            value={channelId}
            onChange={(event) => setChannelId(event.target.value)}
            placeholder="channel-1"
            autoComplete="off"
          />
        </label>
        <div className="actions">
          <button
            type="button"
            className="ghost"
            onClick={() =>
              run(() =>
                desk.hardware.hardwareReset("robot-007", channelId || "channel-robot", "attempt", desk.nowMs),
              )
            }
          >
            Robot hardware reset
          </button>
          <button
            type="button"
            onClick={() =>
              run(() =>
                desk.hardware.hardwareReset(
                  "human-001",
                  channelId,
                  "Operator checked the chain. This is not an actuator enable.",
                  desk.nowMs,
                ),
              )
            }
          >
            Operator hardware reset
          </button>
          <button type="button" className="ghost" onClick={() => run(() => desk.hardware.reportFeedback(false, desk.nowMs))}>
            Feedback off
          </button>
          <button type="button" onClick={() => run(() => desk.hardware.reportFeedback(true, desk.nowMs))}>
            Feedback energized
          </button>
          <button
            type="button"
            onClick={() =>
              run(() => {
                const result = desk.hardware.actuatorCommand()
                const power = desk.hardware.evaluate(desk.nowMs).motionPower ? "on" : "off"
                throw new Error(`${result.code}. Motion power in the model is ${power}.`)
              })
            }
          >
            Request actuator torque
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="split-head">
          <h2>Synthetic warehouse</h2>
          <p className="note">{vision.gate}</p>
        </div>
        <canvas ref={canvasRef} className="viewport" />
        <p className="note">
          Painted rectangles and constant depth. Not a camera image and not a trained detector.
          Mean localization error{" "}
          {vision.meanErrorM === null ? "is not reported" : `is ${(vision.meanErrorM * 1000).toFixed(1)} mm`} on this
          idealized frame. That number is not a safety margin.
        </p>
        <div className="actions">
          <button type="button" onClick={() => setRobotAllowed(true)}>
            Ideal labels
          </button>
          <button type="button" className="ghost" onClick={() => setRobotAllowed(false)}>
            Wrong robot
          </button>
        </div>
        <p className="note">
          {vision.exported
            ? "Latch is clear, so this simulation report can be exported. It still cannot move an actuator."
            : "Export is blocked. The planner does not advance, and physical execution stays off."}
        </p>
        <h3>Recorded depth-fault sweep</h3>
        <p className="note">
          {faultSweep.detector} Noise here is on depth only. The boxes stay the ones the simulator already knew.
          Physical execution: {faultSweep.physicalExecutionEnabled ? "enabled" : "disabled"}.
        </p>
        <table className="sweep">
          <thead>
            <tr>
              <th>Noise</th>
              <th>Missing</th>
              <th>Seed</th>
              <th>Mean</th>
              <th>Missed</th>
            </tr>
          </thead>
          <tbody>
            {faultSweep.results.map((row) => (
              <tr key={`${row.seed}-${row.noiseM}-${row.missing}`}>
                <td>{row.noiseM.toFixed(2)} m</td>
                <td>{Math.round(row.missing * 100)}%</td>
                <td>{row.seed}</td>
                <td>{row.meanMm.toFixed(1)} mm</td>
                <td>{row.missed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {banner ? <p className="banner">{banner}</p> : null}

      <div className="desk-grid">
        <section className="panel">
          <h2>Report</h2>
          <div className="actions">
            <button
              type="button"
              onClick={() =>
                run(() =>
                  desk.report({
                    robotId: "robot-007",
                    code: "SIGNATURE_INVALID",
                    description: "Policy signature verification failed",
                    evidence: { policy_id: "policy-demo" },
                    policyRevision: 4,
                  }),
                )
              }
            >
              Signature failure
            </button>
            <button
              type="button"
              onClick={() =>
                run(() =>
                  desk.report({
                    robotId: "robot-007",
                    code: "UNAPPROVED_BEHAVIOR",
                    description: "Unapproved grasp offered as shared experience",
                    evidence: { action: "unknown_action" },
                    policyRevision: 4,
                    memoryRecordId: "experience-123",
                  }),
                )
              }
            >
              Quarantine grasp memory
            </button>
            <button
              type="button"
              onClick={() =>
                run(() =>
                  desk.report({
                    robotId: "robot-007",
                    code: "AUDIT_INTEGRITY_FAILURE",
                    description: "Evidence could not be serialized",
                    evidence: { circular: true },
                    policyRevision: 3,
                  }),
                )
              }
            >
              Undigestible evidence
            </button>
            <button
              type="button"
              className="ghost"
              onClick={() =>
                run(async () => {
                  desk.failQuarantineWrite = true
                  try {
                    await desk.report({
                      robotId: "robot-007",
                      code: "UNAPPROVED_BEHAVIOR",
                      description: "Quarantine write failed",
                      evidence: { action: "unknown_action" },
                      policyRevision: 4,
                      memoryRecordId: "experience-keep",
                    })
                  } finally {
                    desk.failQuarantineWrite = false
                  }
                })
              }
            >
              Fail the quarantine write
            </button>
          </div>
          <p className="note">
            Containment runs before the digest. If the evidence cannot be hashed, the inhibit
            still stands and the digest is marked unavailable.
          </p>
        </section>

        <section className="panel">
          <h2>Human review</h2>
          <p className="note">
            {latest
              ? `Open incident ${latest.incidentId}`
              : "Report an incident before review. An agent cannot approve one."}
          </p>
          <label>
            Review id
            <input
              value={reviewId}
              onChange={(event) => setReviewId(event.target.value)}
              placeholder="review-001"
              autoComplete="off"
            />
          </label>
          <div className="actions">
            <button
              type="button"
              className="ghost"
              onClick={() =>
                run(() => {
                  if (!latest) throw new Error("Unknown incident.")
                  desk.approveReview(latest.incidentId, "agent-001", reviewId || "review-agent", "reject")
                })
              }
            >
              Review as agent
            </button>
            <button
              type="button"
              onClick={() =>
                run(() => {
                  if (!latest) throw new Error("Unknown incident.")
                  desk.approveReview(
                    latest.incidentId,
                    "human-001",
                    reviewId,
                    "investigated — memory stays quarantined",
                  )
                })
              }
            >
              Review as human-001
            </button>
          </div>
          <label>
            Reset authorization
            <input
              value={authId}
              onChange={(event) => setAuthId(event.target.value)}
              placeholder="approval-201"
              autoComplete="off"
            />
          </label>
          <div className="actions">
            <button type="button" onClick={() => run(() => desk.killSwitch.engage("robot-007", "Operator inhibit"))}>
              Robot inhibit
            </button>
            <button
              type="button"
              onClick={() =>
                run(() =>
                  desk.killSwitch.reset(
                    "human-001",
                    authId,
                    "Reviewed the incident. This does not resume the task.",
                  ),
                )
              }
            >
              Human reset
            </button>
          </div>
          <p className="note">Software reset does not close the E-stop loop or enable torque.</p>
        </section>
      </div>

      <section className="panel">
        <div className="split-head">
          <h2>Shared memory</h2>
          <button type="button" className="ghost" onClick={() => run(() => desk.submitStep())}>
            Submit a new simulation step
          </button>
        </div>
        <p className="task">{snap.task}</p>
        <ul className="memory">
          {snap.memories.map((row) => {
            const visible = snap.retrieved.includes(row.id)
            return (
              <li key={row.id}>
                <span>
                  <strong>{row.id}</strong>
                  <small>{row.label}</small>
                </span>
                <em className={visible ? "ok" : "held"}>{visible ? "Retrieved" : row.status}</em>
              </li>
            )
          })}
        </ul>
        <p className="note">
          Retrieval returns only VALIDATED rows, and only while the latch is clear. Review does
          not put a quarantined row back.
        </p>
      </section>

      <div className="desk-grid">
        <section className="panel">
          <h2>Incidents</h2>
          {snap.incidents.length === 0 ? <p className="note">None yet. The swarm starts inhibited.</p> : null}
          <ul className="cards">
            {snap.incidents.map((incident) => (
              <li key={incident.incidentId}>
                <span className="code">{incident.code}</span>
                <p>{incident.description}</p>
                <p className="meta">
                  {incident.severity} · {incident.status} · rev {incident.policyRevision}
                </p>
                <p className="meta">Digest {incident.evidenceDigest.slice(0, 16)}</p>
                <p className="meta">{incident.actions.join(" · ")}</p>
              </li>
            ))}
          </ul>
        </section>
        <section className="panel">
          <h2>Authority log</h2>
          <ul className="log">
            {snap.audit.map((event) => (
              <li key={`${event.action}-${event.revision}`}>
                <span>{event.action}</span>
                <p>
                  {event.actorId} · rev {event.revision}
                  <br />
                  {event.reason}
                </p>
              </li>
            ))}
            {snap.ledger.map((row, index) => (
              <li key={`${row.eventType}-${index}`}>
                <span>{row.eventType}</span>
                <p>
                  {row.actorId}
                  <br />
                  {row.reason}
                </p>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="panel checks">
        <h2>Local checks</h2>
        <ul>
          {checks.length === 0 ? <li>Running the incident checks…</li> : null}
          {checks.map((check) => (
            <li key={check.name} className={check.pass ? "ok" : "held"}>
              <strong>{check.pass ? "Pass" : "Fail"}</strong>
              <span>
                {check.name}
                <small>{check.detail}</small>
              </span>
            </li>
          ))}
        </ul>
      </section>

      <footer className="limits">
        <p>
          This desk is an in-browser model of the Python incident engine. It does not stop a
          physical robot, authenticate a person, or prove that a disconnected robot received the
          inhibit. The hardware chain is the same kind of model: a series contact check, not a
          safety-rated relay. Closing it in this page does not energize a robot.
        </p>
      </footer>
    </main>
  )
}

function CommandPanel({ view, onChoose }: { view: GateView; onChoose: (mode: GateCase) => void }) {
  return (
    <section className="panel" aria-live="polite">
      <div className="split-head">
        <h2>Command gateway</h2>
        <p className={view.simulationPermitted ? "note ok" : "note held"}>{view.code}</p>
      </div>
      <p className="note">
        Stage: {view.stage}. {view.code}. Simulation event recorded: {view.simulationPermitted ? "yes" : "no"}. Schema
        is checked before replay reservation. Physical execution stays unauthorized.
      </p>
      <div className="actions">
        <button type="button" className="ghost" onClick={() => onChoose("startup")}>
          Startup inhibit
        </button>
        <button type="button" onClick={() => onChoose("admit")}>
          Record simulation
        </button>
        <button type="button" onClick={() => onChoose("execute")}>
          Execute recorded
        </button>
        <button type="button" className="ghost" onClick={() => onChoose("schema")}>
          Bad operation
        </button>
        <button type="button" className="ghost" onClick={() => onChoose("replay")}>
          Replay command
        </button>
        <button type="button" className="ghost" onClick={() => onChoose("tamper")}>
          Tamper signature
        </button>
        <button type="button" className="ghost" onClick={() => onChoose("revoked")}>
          Revoked key
        </button>
        <button type="button" className="ghost" onClick={() => onChoose("observed")}>
          Claim observed
        </button>
        <button type="button" className="ghost" onClick={() => onChoose("stale")}>
          Stale epoch
        </button>
      </div>
    </section>
  )
}

function RecoveryPanel({
  mode,
  reviewed,
  onMode,
  onReviewed,
  onRun,
}: {
  mode: RecoveryCase
  reviewed: boolean
  onMode: (mode: RecoveryCase) => void
  onReviewed: (value: boolean) => void
  onRun: () => void
}) {
  const [ran, setRan] = useState(false)
  const view = ran ? runSwarmRecovery(mode) : reviewRecovery(mode, reviewed)
  return (
    <section className="panel" aria-live="polite">
      <div className="split-head">
        <h2>Swarm recovery</h2>
        <p className={view.mayContinue ? "note ok" : "note held"}>{ran ? "Held" : view.status}</p>
      </div>
      <p className="note">
        {view.decision}. Simulation may continue: {view.mayContinue ? "yes" : "no"}. Physical execution stays
        unauthorized. A recorded review is not an authenticated human approval.
      </p>
      <p className="note">{view.issues.length ? view.issues.join(" · ") : "No consistency issues in this snapshot."}</p>
      <div className="actions">
        <button
          type="button"
          onClick={() => {
            setRan(true)
            onRun()
          }}
        >
          Run recovery
        </button>
        <button type="button" onClick={() => onMode("clean")}>
          Clean snapshot
        </button>
        <button type="button" className="ghost" onClick={() => onMode("expired")}>
          Expired lease
        </button>
        <button type="button" className="ghost" onClick={() => onMode("two-owners")}>
          Two owners
        </button>
        <button type="button" className="ghost" onClick={() => onMode("missing-beat")}>
          Missing heartbeat
        </button>
        <button type="button" onClick={() => onReviewed(!reviewed)}>
          {reviewed ? "Clear review record" : "Record review"}
        </button>
      </div>
    </section>
  )
}

function Contact({
  name,
  closed,
  shut = "Closed",
  open = "Open",
}: {
  name: string
  closed: boolean
  shut?: string
  open?: string
}) {
  return (
    <li className={closed ? "contact is-shut" : "contact is-open"}>
      <strong>{name}</strong>
      <span>{closed ? shut : open}</span>
    </li>
  )
}
