export interface ReplayItem {
  id: string
  kind: "EVENT" | "SEQUENCE_GAP" | "CLOCK_REGRESSION"
  label: string
  evidenceClass: "OBSERVED" | "INFERRED" | "SIMULATED" | "UNKNOWN" | null
  detail: string
}

export const replayItems: ReplayItem[] = [
  {
    id: "sensor",
    kind: "EVENT",
    label: "0 ms · SENSOR_INPUT",
    evidenceClass: "SIMULATED",
    detail: "Synthetic frame reference. This label is not a camera recording.",
  },
  {
    id: "perception",
    kind: "EVENT",
    label: "40 ms · PERCEPTION_RESULT",
    evidenceClass: "INFERRED",
    detail: "Object hypothesis from the synthetic frame. Confidence is not proof.",
  },
  {
    id: "gap",
    kind: "SEQUENCE_GAP",
    label: "SEQUENCE_GAP",
    evidenceClass: null,
    detail: "robot-sim-01: missing sequence number 3. No replacement observation was created.",
  },
  {
    id: "world",
    kind: "EVENT",
    label: "65 ms · WORLD_MODEL_UPDATE",
    evidenceClass: "SIMULATED",
    detail: "Predicted pose. It is not promoted to an observation.",
  },
  {
    id: "authority",
    kind: "EVENT",
    label: "80 ms · AUTHORITY_STATE",
    evidenceClass: "UNKNOWN",
    detail: "Inhibit revision recorded separately. Replay does not clear it.",
  },
]
