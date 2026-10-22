import numpy as np
import pytest

from optimus_swarm.detection_metrics import box_iou, evaluate_detections
from optimus_swarm.fault_injection import FaultConfig, inject_sensor_faults
from optimus_swarm.hardware_interlock import HardwareSafetyChain
from optimus_swarm.perception_benchmark import evaluate_localization
from optimus_swarm.rgbd_perception import RGBDPerception, StaticTestDetector
from optimus_swarm.synthetic_scene import make_warehouse_scene


def test_identical_boxes_have_iou_one():
    box = (10, 10, 50, 50)
    assert box_iou(box, box) == pytest.approx(1.0)


def test_disjoint_boxes_have_iou_zero():
    assert box_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


def test_fault_injection_is_reproducible():
    scene = make_warehouse_scene(timestamp_ms=1000)
    config = FaultConfig(depth_noise_sigma_m=0.02, missing_depth_fraction=0.15, seed=123)

    first = inject_sensor_faults(scene.frame, config)
    second = inject_sensor_faults(scene.frame, config)

    np.testing.assert_equal(first.frame.depth_m, second.frame.depth_m)
    assert first.injected_faults == second.injected_faults


def test_invalid_fault_parameters_are_rejected():
    with pytest.raises(ValueError):
        FaultConfig(missing_depth_fraction=1.5).validate()


def test_detection_metrics_count_false_positives():
    scene = make_warehouse_scene(timestamp_ms=1000)
    truth = list(scene.detections)
    predictions = list(scene.detections)

    extra = type(predictions[0])(
        object_id="unknown-999",
        class_name="box",
        bbox_xyxy=(0, 0, 20, 20),
        confidence=0.8,
    )
    predictions.append(extra)

    report = evaluate_detections(predictions=predictions, ground_truth=truth, iou_threshold=0.5)

    assert report.true_positives == len(truth)
    assert report.false_positives == 1
    assert report.false_negatives == 0
    assert report.precision < 1.0
    assert report.recall == pytest.approx(1.0)


def test_faulted_benchmark_cannot_authorize_motion():
    scene = make_warehouse_scene(timestamp_ms=1000)
    faulted = inject_sensor_faults(
        scene.frame,
        FaultConfig(depth_noise_sigma_m=0.02, missing_depth_fraction=0.1, seed=7),
    )
    result = RGBDPerception(
        detector=StaticTestDetector(list(scene.detections)),
        allowed_robots={"robot-001"},
        allowed_scenes={"warehouse-synthetic-v1"},
    ).process(faulted.frame, now_ms=1000)
    report = evaluate_localization(result, scene.ground_truth)

    assert report.source == "SIMULATION_ONLY"
    assert "DEPTH_GAUSSIAN_NOISE" in faulted.injected_faults
    assert HardwareSafetyChain({"human-001"}).actuator_command("track-faulted-object") == (
        False,
        "NO_SAFETY_RATED_OUTPUT",
    )
