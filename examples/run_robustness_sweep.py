import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from optimus_swarm.fault_injection import FaultConfig, inject_sensor_faults
from optimus_swarm.perception_benchmark import evaluate_localization
from optimus_swarm.rgbd_perception import RGBDPerception, StaticTestDetector
from optimus_swarm.synthetic_scene import make_warehouse_scene


def run_case(noise_sigma, missing_fraction, seed):
    scene = make_warehouse_scene(timestamp_ms=1000)
    fault_result = inject_sensor_faults(
        scene.frame,
        FaultConfig(
            depth_noise_sigma_m=noise_sigma,
            missing_depth_fraction=missing_fraction,
            occlusion_fraction=0.0,
            seed=seed,
        ),
    )

    # This stub returns the scene's predefined boxes. It does not
    # re-detect objects from the altered RGB/depth data.
    detector = StaticTestDetector(list(scene.detections))
    pipeline = RGBDPerception(
        detector=detector,
        allowed_robots={"robot-001"},
        allowed_scenes={"warehouse-synthetic-v1"},
        max_age_ms=500,
    )
    result = pipeline.process(fault_result.frame, now_ms=1000)
    report = evaluate_localization(result, scene.ground_truth)

    return {
        "source": "SIMULATION_ONLY",
        "seed": seed,
        "noise_sigma_m": noise_sigma,
        "missing_depth_fraction": missing_fraction,
        "injected_faults": list(fault_result.injected_faults),
        "status": report.status,
        "matched_objects": report.matched_objects,
        "missed_objects": report.missed_objects,
        "false_positive_objects": report.false_positive_objects,
        "mean_error_m": report.mean_error_m,
        "max_error_m": report.max_error_m,
    }


def main():
    cases = [
        (0.00, 0.00, 7),
        (0.01, 0.00, 7),
        (0.03, 0.10, 7),
        (0.05, 0.30, 7),
        (0.05, 0.30, 21),
    ]
    results = [run_case(noise, missing, seed) for noise, missing, seed in cases]
    print(
        json.dumps(
            {
                "benchmark": "OMEGA-GUARD RGB-D fault sweep",
                "benchmark_version": "0.1",
                "physical_execution_enabled": False,
                "detector": "StaticTestDetector — boxes are not re-detected from the altered image",
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
