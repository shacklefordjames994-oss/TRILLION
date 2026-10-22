import numpy as np

from optimus_swarm.hardware_interlock import HardwareSafetyChain
from optimus_swarm.integrity import TamperEvidentLedger
from optimus_swarm.kill_switch import HumanAuthorityKillSwitch
from optimus_swarm.perception_gateway import PathOption, PerceptionGateway, compare_simulated_paths
from optimus_swarm.rgbd_perception import (
    CameraIntrinsics,
    Detection2D,
    RGBDFrame,
    RGBDPerception,
    StaticTestDetector,
)
from optimus_swarm.virtual_tracking import VirtualObjectTracker


def make_frame(timestamp_ms=1000, depth_value=2.0):
    width, height = 32, 24
    intrinsics = CameraIntrinsics(
        fx=20.0,
        fy=20.0,
        cx=width / 2,
        cy=height / 2,
        width=width,
        height=height,
    )
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    depth = np.full((height, width), depth_value, dtype=np.float32)
    transform = np.eye(4, dtype=np.float64)

    detection = Detection2D(
        object_id="box-1",
        class_name="box",
        bbox_xyxy=(8, 5, 24, 19),
        confidence=0.95,
    )

    return RGBDFrame(
        frame_id=f"frame-{timestamp_ms}",
        robot_id="robot-001",
        scene_id="warehouse-sim",
        timestamp_ms=timestamp_ms,
        source="SIMULATED_RENDER",
        rgb=rgb,
        depth_m=depth,
        intrinsics=intrinsics,
        camera_to_world=transform,
    ), detection


def make_perception(detection):
    return RGBDPerception(
        detector=StaticTestDetector([detection]),
        allowed_robots={"robot-001"},
        allowed_scenes={"warehouse-sim"},
    )


def test_valid_rgbd_frame_projects_object():
    frame, detection = make_frame()
    result = make_perception(detection).process(frame, now_ms=1100)

    assert result.accepted
    assert len(result.objects) == 1
    obj = result.objects[0]
    assert obj.provenance == "SIMULATED_RENDER"
    assert abs(obj.position_world_xyz[2] - 2.0) < 1e-6


def test_stale_frame_is_rejected():
    frame, detection = make_frame(timestamp_ms=1000)
    result = make_perception(detection).process(frame, now_ms=2000)

    assert not result.accepted
    assert result.code == "STALE_FRAME"


def test_invalid_depth_skips_object():
    frame, detection = make_frame(depth_value=float("nan"))
    result = make_perception(detection).process(frame, now_ms=1100)

    assert result.accepted
    assert result.objects == ()


def test_invalid_transform_is_rejected():
    frame, detection = make_frame()
    invalid_transform = frame.camera_to_world.copy()
    invalid_transform[0, 0] = 2.0

    frame = RGBDFrame(**{**frame.__dict__, "camera_to_world": invalid_transform})
    result = make_perception(detection).process(frame, now_ms=1100)

    assert not result.accepted
    assert result.code == "INVALID_TRANSFORM"


def test_tracker_estimates_simulated_velocity():
    frame1, detection1 = make_frame(timestamp_ms=1000, depth_value=2.0)
    frame2, detection2 = make_frame(timestamp_ms=1100, depth_value=2.1)

    p1 = make_perception(detection1).process(frame1, now_ms=1100)
    p2 = make_perception(detection2).process(frame2, now_ms=1200)

    tracker = VirtualObjectTracker()
    first = tracker.update(p1, timestamp_ms=1000)
    second = tracker.update(p2, timestamp_ms=1100)

    assert first[0].velocity_xyz_mps is None
    assert second[0].velocity_xyz_mps is not None
    assert second[0].velocity_xyz_mps[2] > 0


def test_gateway_blocks_a_latched_swarm():
    frame, detection = make_frame()
    result = make_perception(detection).process(frame, now_ms=1100)
    switch = HumanAuthorityKillSwitch({"human-001"})
    ledger = TamperEvidentLedger(b"g" * 32)

    allowed, payload = PerceptionGateway(switch, ledger).authorize(result, "robot-001", "warehouse-sim")

    assert result.accepted
    assert allowed is False
    assert payload == "KILL_SWITCH_LATCHED"


def test_gateway_accepts_simulation_data_only():
    frame, detection = make_frame()
    result = make_perception(detection).process(frame, now_ms=1100)
    switch = HumanAuthorityKillSwitch({"human-001"})
    switch.reset("human-001", "approval-rgbd", "simulation review")
    ledger = TamperEvidentLedger(b"g" * 32)

    allowed, envelope = PerceptionGateway(switch, ledger).authorize(result, "robot-001", "warehouse-sim")

    assert allowed is True
    assert envelope.status == "SIMULATION_ONLY"
    assert envelope.source == "SIMULATED_RENDER"
    assert envelope.object_count == 1
    assert HardwareSafetyChain({"human-001"}).actuator_command("follow-track") == (
        False,
        "NO_SAFETY_RATED_OUTPUT",
    )


def test_path_comparison_does_not_command_motion():
    ok, report = compare_simulated_paths(
        (
            PathOption("wide", 0.40, 0.05),
            PathOption("tight", 0.08, 0.02),
        )
    )

    assert ok is True
    assert report["preferred"] == "wide"
    assert report["human_review"] is True
    assert report["actuator"] is False
