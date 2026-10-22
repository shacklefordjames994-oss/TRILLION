import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from optimus_swarm.perception_benchmark import evaluate_localization
from optimus_swarm.perception_visualizer import show_perception_overlay
from optimus_swarm.rgbd_perception import RGBDPerception, StaticTestDetector
from optimus_swarm.synthetic_scene import make_warehouse_scene


def main():
    now_ms = 1000
    scene = make_warehouse_scene(timestamp_ms=now_ms)

    # The test detector uses simulator-generated labels.
    # This is a plumbing test, not a vision-model accuracy test.
    detector = StaticTestDetector(list(scene.detections))
    perception = RGBDPerception(
        detector=detector,
        allowed_robots={"robot-001"},
        allowed_scenes={"warehouse-synthetic-v1"},
        max_age_ms=500,
    )
    result = perception.process(scene.frame, now_ms=now_ms)
    report = evaluate_localization(result, scene.ground_truth)

    print(
        json.dumps(
            {
                "status": report.status,
                "source": report.source,
                "matched_objects": report.matched_objects,
                "ground_truth_objects": report.ground_truth_objects,
                "detected_objects": report.detected_objects,
                "missed_objects": report.missed_objects,
                "false_positive_objects": report.false_positive_objects,
                "mean_error_m": report.mean_error_m,
                "max_error_m": report.max_error_m,
            },
            indent=2,
        )
    )

    overlay = show_perception_overlay(
        scene,
        result,
        save_path=os.path.join("artifacts", "warehouse_overlay.png"),
    )
    print(json.dumps({"overlay": overlay, "physical_performance": False}))


if __name__ == "__main__":
    main()
