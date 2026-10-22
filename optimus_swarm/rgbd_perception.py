from dataclasses import dataclass
from typing import Protocol
import math

import numpy as np


@dataclass(frozen=True)
class CameraIntrinsics:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int


@dataclass(frozen=True)
class Detection2D:
    object_id: str
    class_name: str
    # Pixel bounds: x_min, y_min, x_max, y_max
    bbox_xyxy: tuple[int, int, int, int]
    confidence: float


@dataclass(frozen=True)
class RGBDFrame:
    frame_id: str
    robot_id: str
    scene_id: str
    timestamp_ms: int
    source: str
    rgb: np.ndarray
    depth_m: np.ndarray
    intrinsics: CameraIntrinsics
    # Homogeneous transform: camera coordinates -> world coordinates
    camera_to_world: np.ndarray


@dataclass(frozen=True)
class Object3D:
    object_id: str
    class_name: str
    position_world_xyz: tuple[float, float, float]
    confidence: float
    depth_spread_m: float
    provenance: str


@dataclass(frozen=True)
class RGBDResult:
    accepted: bool
    code: str
    frame_id: str
    objects: tuple[Object3D, ...]
    reason: str


class Detector(Protocol):
    def detect(self, rgb: np.ndarray) -> list[Detection2D]:
        ...


class StaticTestDetector:
    """Deterministic detector for tests; not a trained CV model."""

    def __init__(self, detections: list[Detection2D]):
        self._detections = detections

    def detect(self, rgb: np.ndarray) -> list[Detection2D]:
        return list(self._detections)


class RGBDPerception:
    def __init__(
        self,
        detector: Detector,
        allowed_robots: set[str],
        allowed_scenes: set[str],
        max_age_ms: int = 500,
        min_depth_m: float = 0.1,
        max_depth_m: float = 20.0,
        min_valid_depth_fraction: float = 0.25,
    ):
        if max_age_ms <= 0:
            raise ValueError("max_age_ms must be positive")
        if not 0 < min_depth_m < max_depth_m:
            raise ValueError("Invalid depth range")
        if not 0 < min_valid_depth_fraction <= 1:
            raise ValueError("Invalid valid-depth fraction")

        self.detector = detector
        self.allowed_robots = frozenset(allowed_robots)
        self.allowed_scenes = frozenset(allowed_scenes)
        self.max_age_ms = max_age_ms
        self.min_depth_m = min_depth_m
        self.max_depth_m = max_depth_m
        self.min_valid_depth_fraction = min_valid_depth_fraction

    @staticmethod
    def _valid_transform(transform: np.ndarray) -> bool:
        if not isinstance(transform, np.ndarray):
            return False
        if transform.shape != (4, 4):
            return False
        if not np.isfinite(transform).all():
            return False
        if not np.allclose(transform[3], [0, 0, 0, 1], atol=1e-6):
            return False

        rotation = transform[:3, :3]
        return np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3) and np.isclose(
            np.linalg.det(rotation), 1.0, atol=1e-3
        )

    def _reject(self, frame: RGBDFrame, code: str, reason: str):
        return RGBDResult(False, code, getattr(frame, "frame_id", "UNKNOWN"), (), reason)

    def process(self, frame: RGBDFrame, now_ms: int) -> RGBDResult:
        if frame.robot_id not in self.allowed_robots:
            return self._reject(frame, "ROBOT_NOT_ALLOWED", "Robot is not allowlisted.")

        if frame.scene_id not in self.allowed_scenes:
            return self._reject(frame, "SCENE_NOT_ALLOWED", "Scene is not allowlisted.")

        if frame.source != "SIMULATED_RENDER":
            return self._reject(
                frame,
                "SOURCE_NOT_ALLOWED",
                "This pipeline accepts virtual rendered frames only.",
            )

        if frame.timestamp_ms > now_ms:
            return self._reject(frame, "FUTURE_FRAME", "Frame timestamp is in the future.")

        if now_ms - frame.timestamp_ms > self.max_age_ms:
            return self._reject(frame, "STALE_FRAME", "Frame is too old.")

        k = frame.intrinsics
        if min(k.fx, k.fy) <= 0 or min(k.width, k.height) <= 0:
            return self._reject(frame, "INVALID_INTRINSICS", "Camera calibration is invalid.")

        if frame.rgb.shape != (k.height, k.width, 3):
            return self._reject(frame, "INVALID_RGB_SHAPE", "RGB dimensions do not match calibration.")

        if frame.depth_m.shape != (k.height, k.width):
            return self._reject(frame, "INVALID_DEPTH_SHAPE", "Depth dimensions do not match RGB.")

        if not self._valid_transform(frame.camera_to_world):
            return self._reject(
                frame,
                "INVALID_TRANSFORM",
                "Camera-to-world transform is not a valid rigid transform.",
            )

        if not np.issubdtype(frame.depth_m.dtype, np.number):
            return self._reject(frame, "INVALID_DEPTH_TYPE", "Depth map must be numeric.")

        try:
            detections = self.detector.detect(frame.rgb)
        except Exception:
            return self._reject(frame, "DETECTOR_FAILURE", "Detector failed; frame rejected.")

        objects = []
        seen_ids = set()

        for det in detections:
            if not det.object_id or not det.class_name or det.object_id in seen_ids:
                return self._reject(
                    frame,
                    "INVALID_DETECTION",
                    "Detection IDs/classes must be present and unique.",
                )
            seen_ids.add(det.object_id)

            if not math.isfinite(det.confidence) or not 0.0 <= det.confidence <= 1.0:
                return self._reject(
                    frame,
                    "INVALID_CONFIDENCE",
                    "Detection confidence must be in [0, 1].",
                )

            x1, y1, x2, y2 = det.bbox_xyxy
            if not (0 <= x1 < x2 <= k.width and 0 <= y1 < y2 <= k.height):
                return self._reject(frame, "INVALID_BBOX", "Bounding box is outside image bounds.")

            # Use the central 50% of the bounding box to reduce
            # contamination from edges and background pixels.
            inner_x1 = x1 + (x2 - x1) // 4
            inner_x2 = x2 - (x2 - x1) // 4
            inner_y1 = y1 + (y2 - y1) // 4
            inner_y2 = y2 - (y2 - y1) // 4

            depth_region = frame.depth_m[inner_y1:inner_y2, inner_x1:inner_x2]
            valid = depth_region[
                np.isfinite(depth_region)
                & (depth_region >= self.min_depth_m)
                & (depth_region <= self.max_depth_m)
            ]

            total = depth_region.size
            if total == 0 or len(valid) / total < self.min_valid_depth_fraction:
                continue

            z = float(np.median(valid))
            spread = float(np.median(np.abs(valid - z)))

            # Median pixel coordinate of the detection box.
            u = (x1 + x2 - 1) / 2.0
            v = (y1 + y2 - 1) / 2.0

            # Pinhole camera projection. Camera axes:
            # X right, Y down, Z forward.
            point_camera = np.array(
                [
                    (u - k.cx) * z / k.fx,
                    (v - k.cy) * z / k.fy,
                    z,
                    1.0,
                ]
            )

            point_world = frame.camera_to_world @ point_camera
            xyz = point_world[:3]

            if not np.isfinite(xyz).all():
                return self._reject(
                    frame,
                    "NONFINITE_PROJECTION",
                    "3D projection produced invalid coordinates.",
                )

            objects.append(
                Object3D(
                    object_id=det.object_id,
                    class_name=det.class_name,
                    position_world_xyz=tuple(float(v) for v in xyz),
                    confidence=float(det.confidence),
                    depth_spread_m=spread,
                    provenance="SIMULATED_RENDER",
                )
            )

        return RGBDResult(
            True,
            "RGBD_PERCEPTION_ACCEPTED",
            frame.frame_id,
            tuple(objects),
            "Projected virtual RGB-D detections; not physical observations.",
        )
