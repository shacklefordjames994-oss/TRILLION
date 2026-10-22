export interface TaskView {
  status: string
  worker: string
  generation: number
  reason: string
  admission: string
  physicalExecutionAuthorized: false
}

export class SimCoordinator {
  private status = "NONE"
  private worker = ""
  private generation = 0
  private expiresAt = 0
  private reason = "No simulated task is submitted."
  private busy = new Set<string>()
  now = 1000

  private expire() {
    if (this.status === "LEASED" && this.now >= this.expiresAt) {
      this.busy.delete(this.worker)
      this.status = "PENDING"
      this.worker = ""
      this.reason = "LEASE_EXPIRED"
    }
  }

  submit() {
    if (this.status !== "NONE" && this.status !== "CANCELLED" && this.status !== "COMPLETED") {
      this.reason = "DUPLICATE_TASK_ID"
      return
    }
    this.status = "PENDING"
    this.worker = ""
    this.generation = 0
    this.reason = "TASK_SUBMITTED"
  }

  assign(workerId: string) {
    this.expire()
    if (this.status !== "PENDING") {
      this.reason = this.status === "NONE" ? "UNKNOWN_TASK" : "TASK_NOT_PENDING"
      return
    }
    if (this.busy.has(workerId)) {
      this.reason = "WORKER_NOT_AVAILABLE"
      return
    }
    this.generation += 1
    this.status = "LEASED"
    this.worker = workerId
    this.expiresAt = this.now + 1000
    this.busy.add(workerId)
    this.reason = "LEASE_ISSUED"
  }

  complete(workerId: string) {
    this.expire()
    if (this.status !== "LEASED") {
      this.reason = "NO_ACTIVE_LEASE"
      return
    }
    if (workerId !== this.worker) {
      this.reason = "LEASE_IDENTITY_MISMATCH"
      return
    }
    this.busy.delete(workerId)
    this.status = "COMPLETED"
    this.worker = ""
    this.reason = "TASK_COMPLETED"
  }

  cancel(human: boolean) {
    if (!human) {
      this.reason = "HUMAN_AUTHORITY_REQUIRED"
      return
    }
    if (this.status === "COMPLETED" || this.status === "CANCELLED" || this.status === "NONE") {
      this.reason = this.status === "NONE" ? "UNKNOWN_TASK" : "TASK_ALREADY_TERMINAL"
      return
    }
    if (this.worker) this.busy.delete(this.worker)
    this.status = "CANCELLED"
    this.worker = ""
    this.reason = "TASK_CANCELLED"
  }

  advance() {
    this.now += 1000
    this.expire()
  }

  view(latched: boolean): TaskView {
    let admission = "No active lease."
    if (this.status === "LEASED") {
      if (latched) admission = "SAFETY_INHIBIT_ACTIVE"
      else if (this.now >= this.expiresAt) admission = "LEASE_EXPIRED"
      else admission = "SIMULATED_TASK_ADMITTED"
    }
    return {
      status: this.status,
      worker: this.worker || "none",
      generation: this.generation,
      reason: this.reason,
      admission,
      physicalExecutionAuthorized: false,
    }
  }
}
