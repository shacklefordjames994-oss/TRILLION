export interface DurableView {
  status: string
  generation: number
  worker: string
  code: string
  physicalExecutionAuthorized: false
}

export class DurableDesk {
  private status = "PENDING"
  private generation = 0
  private worker = ""
  private leaseId = ""
  private expiresAt = 0
  private completionKey = ""
  private code = "Task is pending. No lease is stored yet."

  assign(workerId: string, now: number) {
    if (this.status === "COMPLETED" || this.status === "CANCELLED") {
      this.code = "TASK_TERMINAL"
      return
    }
    if (this.status === "LEASED" && this.expiresAt > now) {
      this.code = "TASK_ALREADY_LEASED"
      return
    }
    this.generation += 1
    this.status = "LEASED"
    this.worker = workerId
    this.leaseId = `gen-${this.generation}`
    this.expiresAt = now + 500
    this.code = "LEASE_GRANTED"
  }

  complete(workerId: string, generation: number, key: string, now: number) {
    if (this.completionKey && generation === this.generation && this.status === "COMPLETED") {
      this.code = key === this.completionKey ? "IDEMPOTENT_REPLAY" : "CONFLICTING_COMPLETION"
      return
    }
    if (this.status !== "LEASED") {
      this.code = "TASK_NOT_LEASED"
      return
    }
    if (generation !== this.generation) {
      this.code = "STALE_FENCING_TOKEN"
      return
    }
    if (workerId !== this.worker) {
      this.code = "LEASE_IDENTITY_MISMATCH"
      return
    }
    if (this.expiresAt <= now) {
      this.code = "LEASE_EXPIRED"
      return
    }
    this.status = "COMPLETED"
    this.completionKey = key
    this.worker = ""
    this.code = "TASK_COMPLETED"
  }

  view(): DurableView {
    return {
      status: this.status,
      generation: this.generation,
      worker: this.worker || "none",
      code: this.code,
      physicalExecutionAuthorized: false,
    }
  }
}
