from dataclasses import replace

from optimus_swarm.integrity import TamperEvidentLedger
from optimus_swarm.kill_switch import HumanAuthorityKillSwitch
from optimus_swarm.perception_benchmark import evaluate_localization, export_simulation_report
from optimus_swarm.rgbd_perception import RGBDPerception, StaticTestDetector
from optimus_swarm.synthetic_scene import make_warehouse_scene


def test_perfect_simulator_labels_have_low_localization_error():
    scene = make_warehouse_scene(timestamp_ms=1000)
    detector = StaticTestDetector(list(scene.detections))

    pipeline = RGBDPerception(
        detector=detector,
        allowed_robots={"robot-001"},
        allowed_scenes={"warehouse-synthetic-v1"},
    )

    result = pipeline.process(scene.frame, now_ms=1000)
    report = evaluate_localization(result, scene.ground_truth)

    assert report.status == "EVALUATED"
    assert report.matched_objects == len(scene.ground_truth)
    assert report.missed_objects == 0
    assert report.false_positive_objects == 0
    assert report.mean_error_m is not None
    assert report.mean_error_m < 0.05


def test_rejected_frame_does_not_report_localization_success():
    scene = make_warehouse_scene(timestamp_ms=1000)
    detector = StaticTestDetector(list(scene.detections))

    pipeline = RGBDPerception(
        detector=detector,
        allowed_robots={"another-robot"},
        allowed_scenes={"warehouse-synthetic-v1"},
    )

    result = pipeline.process(scene.frame, now_ms=1000)
    report = evaluate_localization(result, scene.ground_truth)

    assert report.status == "PERCEPTION_REJECTED"
    assert report.mean_error_m is None


def test_metrics_are_labeled_simulation_only():
    scene = make_warehouse_scene(timestamp_ms=1000)
    detector = StaticTestDetector(list(scene.detections))

    pipeline = RGBDPerception(
        detector=detector,
        allowed_robots={"robot-001"},
        allowed_scenes={"warehouse-synthetic-v1"},
    )

    result = pipeline.process(scene.frame, now_ms=1000)
    report = evaluate_localization(result, scene.ground_truth)

    assert report.source == "SIMULATION_ONLY"


def test_export_is_blocked_while_latched_or_ledger_is_broken():
    scene = make_warehouse_scene(timestamp_ms=1000)
    pipeline = RGBDPerception(
        detector=StaticTestDetector(list(scene.detections)),
        allowed_robots={"robot-001"},
        allowed_scenes={"warehouse-synthetic-v1"},
    )
    report = evaluate_localization(pipeline.process(scene.frame, now_ms=1000), scene.ground_truth)
    switch = HumanAuthorityKillSwitch({"human-001"})
    ledger = TamperEvidentLedger(b"b" * 32)

    blocked, code = export_simulation_report(report, switch, ledger)
    assert blocked is False
    assert code == "KILL_SWITCH_LATCHED"

    switch.reset("human-001", "approval-bench", "review")
    record = ledger.append("robot-001", "NOTE", "seed")
    ledger._records[0] = replace(record, reason="Altered")
    blocked, code = export_simulation_report(report, switch, ledger)
    assert blocked is False
    assert code == "AUDIT_INTEGRITY_FAILURE"
