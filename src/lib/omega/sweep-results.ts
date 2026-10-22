export const faultSweep = {
  benchmark: "OMEGA-GUARD RGB-D fault sweep",
  benchmarkVersion: "0.1",
  physicalExecutionEnabled: false,
  detector: "StaticTestDetector does not re-read the altered image.",
  results: [
    { seed: 7, noiseM: 0, missing: 0, faults: "none", meanMm: 13.4, maxMm: 14.8, missed: 0 },
    { seed: 7, noiseM: 0.01, missing: 0, faults: "noise", meanMm: 13.4, maxMm: 14.8, missed: 0 },
    { seed: 7, noiseM: 0.03, missing: 0.1, faults: "noise, missing depth", meanMm: 13.5, maxMm: 14.9, missed: 0 },
    { seed: 7, noiseM: 0.05, missing: 0.3, faults: "noise, missing depth", meanMm: 13.6, maxMm: 15.0, missed: 0 },
    { seed: 21, noiseM: 0.05, missing: 0.3, faults: "noise, missing depth", meanMm: 13.5, maxMm: 15.0, missed: 0 },
  ],
} as const
