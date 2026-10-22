export function physicalExecutionPermitted(): false {
  return false
}

export function requestPhysicalExecution(): { permitted: false; code: "PHYSICAL_EXECUTION_INHIBITED" } {
  return { permitted: false, code: "PHYSICAL_EXECUTION_INHIBITED" }
}
