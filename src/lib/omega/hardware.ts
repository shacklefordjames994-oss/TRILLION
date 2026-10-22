export class HardwareStopRequired extends Error {}

export interface ChainStatus {
  estopLoopClosed: boolean
  watchdogClosed: boolean
  guardClosed: boolean
  feedbackAgrees: boolean
  faultLatched: boolean
  motionPower: boolean
  actuatorOutputEnabled: false
  reason: string
}

const UNAVAILABLE: ChainStatus = {
  estopLoopClosed: false,
  watchdogClosed: false,
  guardClosed: false,
  feedbackAgrees: false,
  faultLatched: true,
  motionPower: false,
  actuatorOutputEnabled: false,
  reason: "SAFETY_CHAIN_UNAVAILABLE",
}

export class HardwareSafetyChain {
  static readonly SAFETY_PLC = "safety-plc"

  private readonly operators: Set<string>
  private readonly watchdogMs: number
  private estopPressed = true
  private resetClosed = false
  private guardClosed = true
  private lastPulse: number | null = null
  private feedbackEnergized = false
  private fault = false
  private faultReason = ""
  private readonly used = new Set<string>()

  constructor(resetOperators: string[], watchdogMs = 250) {
    const operators = new Set(resetOperators.map((actor) => actor.trim()).filter((actor) => actor.length > 0))
    if (operators.size === 0) throw new Error("At least one hardware reset operator is required.")
    if (!Number.isInteger(watchdogMs) || watchdogMs <= 0) {
      throw new Error("Watchdog interval must be a positive integer.")
    }
    this.operators = operators
    this.watchdogMs = watchdogMs
  }

  evaluate(nowMs: number): ChainStatus {
    if (!Number.isInteger(nowMs) || nowMs < 0) return { ...UNAVAILABLE }
    const demandedBefore = this.demand(nowMs)
    if (this.feedbackEnergized && !demandedBefore) {
      this.fault = true
      this.resetClosed = false
      this.faultReason = "FEEDBACK_DISAGREES"
    }
    const watchdogClosed = this.watchdogOk(nowMs)
    const demanded = this.demand(nowMs)
    const agrees = this.feedbackEnergized === demanded && !this.fault
    const motion = demanded && this.feedbackEnergized && agrees
    let reason = "CHAIN_OPEN"
    if (this.fault) reason = this.faultReason || "FAULT_LATCHED"
    else if (this.estopPressed) reason = "ESTOP_OPEN"
    else if (!this.resetClosed) reason = "RESET_OPEN"
    else if (!watchdogClosed) reason = "WATCHDOG_OPEN"
    else if (!this.guardClosed) reason = "GUARD_OPEN"
    else if (!this.feedbackEnergized) reason = "FEEDBACK_DEENERGIZED"
    else if (motion) reason = "CHAIN_CLOSED_OUTPUT_STILL_DISABLED"
    return {
      estopLoopClosed: !this.estopPressed,
      watchdogClosed,
      guardClosed: this.guardClosed,
      feedbackAgrees: agrees,
      faultLatched: this.fault,
      motionPower: motion,
      actuatorOutputEnabled: false,
      reason,
    }
  }

  demandStop(actorId: string, reason: string): ChainStatus {
    if (!actorId.trim() || !reason.trim()) throw new Error("Actor and reason are required.")
    this.estopPressed = true
    this.resetClosed = false
    return this.evaluate(this.lastPulse ?? 0)
  }

  releaseEstop(actorId: string): ChainStatus {
    if (!this.operators.has(actorId)) {
      throw new HardwareStopRequired("Only a hardware operator can release the E-stop.")
    }
    this.estopPressed = false
    return this.evaluate(this.lastPulse ?? 0)
  }

  pulse(source: string, nowMs: number): boolean {
    if (source !== HardwareSafetyChain.SAFETY_PLC) return false
    if (!Number.isInteger(nowMs) || nowMs < 0) return false
    this.lastPulse = nowMs
    return true
  }

  openGuard(reason: string): ChainStatus {
    if (!reason.trim()) throw new Error("reason is required.")
    this.guardClosed = false
    this.resetClosed = false
    return this.evaluate(this.lastPulse ?? 0)
  }

  closeGuard(actorId: string): ChainStatus {
    if (!this.operators.has(actorId)) throw new HardwareStopRequired("A robot cannot close a guard.")
    this.guardClosed = true
    return this.evaluate(this.lastPulse ?? 0)
  }

  reportFeedback(energized: boolean, nowMs: number): ChainStatus {
    this.feedbackEnergized = energized
    return this.evaluate(nowMs)
  }

  hardwareReset(actorId: string, channelId: string, reason: string, nowMs: number): ChainStatus {
    if (!this.operators.has(actorId)) {
      throw new HardwareStopRequired("Hardware reset requires an authorized operator.")
    }
    if (!channelId.trim() || !reason.trim()) {
      throw new HardwareStopRequired("A hardware channel id and a reason are required.")
    }
    if (this.estopPressed) throw new HardwareStopRequired("E-stop is still pressed.")
    if (!this.guardClosed) throw new HardwareStopRequired("Guard is open.")
    if (!this.watchdogOk(nowMs)) throw new HardwareStopRequired("Watchdog is open.")
    if (this.feedbackEnergized) throw new HardwareStopRequired("Contactor feedback is still energized.")
    if (this.used.has(channelId.trim())) {
      throw new HardwareStopRequired("Hardware channel id has already been used.")
    }
    this.used.add(channelId.trim())
    this.fault = false
    this.faultReason = ""
    this.resetClosed = true
    return this.evaluate(nowMs)
  }

  actuatorCommand(): { allowed: false; code: "NO_SAFETY_RATED_OUTPUT" } {
    return { allowed: false, code: "NO_SAFETY_RATED_OUTPUT" }
  }

  private watchdogOk(nowMs: number): boolean {
    if (!Number.isInteger(nowMs) || nowMs < 0) return false
    if (this.lastPulse === null || nowMs < this.lastPulse) return false
    return nowMs - this.lastPulse <= this.watchdogMs
  }

  private demand(nowMs: number): boolean {
    return !this.estopPressed && this.resetClosed && this.watchdogOk(nowMs) && this.guardClosed && !this.fault
  }
}
