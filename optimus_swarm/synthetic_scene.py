from dataclasses import dataclass
import numpy as np

from optimus_swarm.rgbd_perception import CameraIntrinsics, Detection2D, RGBDFrame


@dataclass(frozen=True)
class GroundTruthObject:
    object_id: str
    class_name: str
    position_world_xyz: tuple[float, float, float]
    size_xyz: tuple[float, float, float]


@dataclass(frozen=True)
class SyntheticScene:
    scene_id: str
    timestamp_ms: int
    frame: RGBDFrame
    detections: tuple[Detection2D, ...]
    ground_truth: tuple[GroundTruthObject, ...]


def make_warehouse_scene(
    timestamp_ms: int = 1000,
    width: int = 320,
    height: int = 240,
) -> SyntheticScene:
    """
    Generates a deterministic synthetic RGB-D test scene.

    The camera looks along +Z. Objects are axis-aligned test targets
    expressed in the camera frame, so the identity camera-to-world
    transform is intentional for this fixture. This is a simplified
    projection renderer, not a full 3D renderer.
    """
    intrinsics = CameraIntrinsics(
        fx=240.0,
        fy=240.0,
        cx=width / 2.0,
        cy=height / 2.0,
        width=width,
        height=height,
    )

    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[:, :, :] = (40, 45, 52)
    depth = np.full((height, width), np.nan, dtype=np.float32)

    objects = (
        GroundTruthObject("box-001", "box", (-0.35, 0.10, 2.5), (0.45, 0.40, 0.35)),
        GroundTruthObject("crate-002", "crate", (0.40, -0.05, 3.2), (0.55, 0.50, 0.50)),
    )

    detections = []

    for index, obj in enumerate(objects):
        x, y, z = obj.position_world_xyz
        sx, sy, _ = obj.size_xyz

        # Approximate projected box size using the pinhole camera model.
        # Y is down in this camera frame, matching the RGB-D projector.
        u = int(intrinsics.fx * x / z + intrinsics.cx)
        v = int(intrinsics.fy * y / z + intrinsics.cy)
        half_w = max(2, int(intrinsics.fx * sx / (2 * z)))
        half_h = max(2, int(intrinsics.fy * sy / (2 * z)))

        x1 = max(0, u - half_w)
        x2 = min(width, u + half_w)
        y1 = max(0, v - half_h)
        y2 = min(height, v + half_h)

        if x1 >= x2 or y1 >= y2:
            continue

        color = (40, 150, 220) if index == 0 else (210, 140, 40)
        rgb[y1:y2, x1:x2] = color
        depth[y1:y2, x1:x2] = z

        detections.append(
            Detection2D(
                object_id=obj.object_id,
                class_name=obj.class_name,
                bbox_xyxy=(x1, y1, x2, y2),
                confidence=0.99,
            )
        )

    frame = RGBDFrame(
        frame_id=f"synthetic-{timestamp_ms}",
        robot_id="robot-001",
        scene_id="warehouse-synthetic-v1",
        timestamp_ms=timestamp_ms,
        source="SIMULATED_RENDER",
        rgb=rgb,
        depth_m=depth,
        intrinsics=intrinsics,
        camera_to_world=np.eye(4, dtype=np.float64),
    )

    return SyntheticScene(
        scene_id="warehouse-synthetic-v1",
        timestamp_ms=timestamp_ms,
        frame=frame,
        detections=tuple(detections),
        ground_truth=objects,
    )
