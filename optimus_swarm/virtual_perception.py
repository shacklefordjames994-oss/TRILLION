from dataclasses import dataclass
from typing import Literal
import math
import time

SourceType = Literal["SIMULATED_RENDER", "SIMULATED_SCENE_GRAPH"]


@dataclass(frozen=True)
class VirtualObject:
    object_id: str
    class_name: str
    position_xyz: tuple[float, float, float]
    confidence: float
    visible: bool = True


@dataclass(frozen=True)
class VirtualFrame:
    frame_id: str
    robot_id: str
    scene_id: str
    timestamp_ms: int
    coordinate_frame: str
    source: SourceType
    objects: tuple[VirtualObject, ...]


@dataclass(frozen=True)
class PerceivedObject:
    object_id: str
    class_name: str
    position_xyz: tuple[float, float, float]
    confidence: float
    visible: bool
    provenance: str


@dataclass(frozen=True)
class PerceptionResult:
    accepted: bool
    code: str
    frame_id: str
    robot_id: str
    source: str
    observed_at_ms: int
    objects: tuple[PerceivedObject, ...]
    reason: str


@dataclass(frozen=True)
class SpatialRelation:
    subject_id: str
    relation: str
    target_id: str
    distance_m: float | None
    confidence: float
    provenance: str


class VirtualPerception:
    """
    Deterministic perception adapter for virtual/synthetic scenes.
    Not a physical-camera detector or a validated robotics model.
    """

    def __init__(
        self,
        allowed_robots: set[str],
        allowed_scenes: set[str],
        max_frame_age_ms: int = 1000,
    ):
        if max_frame_age_ms <= 0:
            raise ValueError("max_frame_age_ms must be positive")

        self._robots = frozenset(allowed_robots)
        self._scenes = frozenset(allowed_scenes)
        self._max_age_ms = max_frame_age_ms

    def perceive(
        self,
        frame: VirtualFrame,
        now_ms: int | None = None,
    ) -> PerceptionResult:
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms

        def reject(code: str, reason: str):
            return PerceptionResult(
                False,
                code,
                getattr(frame, "frame_id", "UNKNOWN"),
                getattr(frame, "robot_id", "UNKNOWN"),
                getattr(frame, "source", "UNKNOWN"),
                now_ms,
                (),
                reason,
            )

        if frame.robot_id not in self._robots:
            return reject("ROBOT_NOT_ALLOWED", "Robot is not allowlisted.")

        if frame.scene_id not in self._scenes:
            return reject("SCENE_NOT_ALLOWED", "Scene is not allowlisted.")

        if frame.source not in ("SIMULATED_RENDER", "SIMULATED_SCENE_GRAPH"):
            return reject("SOURCE_NOT_ALLOWED", "Source is not a virtual source.")

        if frame.coordinate_frame != "world":
            return reject(
                "COORDINATE_FRAME_UNSUPPORTED",
                "This adapter requires the world coordinate frame.",
            )

        if frame.timestamp_ms > now_ms:
            return reject("FUTURE_FRAME", "Frame timestamp is in the future.")

        if now_ms - frame.timestamp_ms > self._max_age_ms:
            return reject("STALE_FRAME", "Frame exceeds maximum permitted age.")

        if not frame.frame_id or not frame.objects:
            return reject("INVALID_FRAME", "Frame ID or object list is missing.")

        seen_ids = set()
        perceived = []

        for obj in frame.objects:
            if not obj.object_id or not obj.class_name:
                return reject("INVALID_OBJECT", "Object ID/class is missing.")

            if obj.object_id in seen_ids:
                return reject("DUPLICATE_OBJECT_ID", "Object IDs must be unique.")
            seen_ids.add(obj.object_id)

            if len(obj.position_xyz) != 3:
                return reject("INVALID_POSITION", "Position must have 3 values.")

            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in obj.position_xyz):
                return reject(
                    "INVALID_POSITION",
                    "Position must contain finite numeric coordinates.",
                )

            if not isinstance(obj.confidence, (int, float)):
                return reject("INVALID_CONFIDENCE", "Confidence must be numeric.")

            if not 0.0 <= obj.confidence <= 1.0:
                return reject("INVALID_CONFIDENCE", "Confidence must be in [0, 1].")

            perceived.append(
                PerceivedObject(
                    object_id=obj.object_id,
                    class_name=obj.class_name,
                    position_xyz=tuple(float(v) for v in obj.position_xyz),
                    confidence=float(obj.confidence),
                    visible=bool(obj.visible),
                    provenance=frame.source,
                )
            )

        return PerceptionResult(
            accepted=True,
            code="VIRTUAL_PERCEPTION_ACCEPTED",
            frame_id=frame.frame_id,
            robot_id=frame.robot_id,
            source=frame.source,
            observed_at_ms=frame.timestamp_ms,
            objects=tuple(perceived),
            reason="Validated virtual scene data; not a physical observation.",
        )


def derive_spatial_relations(
    result: PerceptionResult,
    near_threshold_m: float = 1.0,
    minimum_confidence: float = 0.5,
) -> tuple[SpatialRelation, ...]:
    if not result.accepted:
        return ()

    if near_threshold_m <= 0:
        raise ValueError("near_threshold_m must be positive")

    objects = [obj for obj in result.objects if obj.visible and obj.confidence >= minimum_confidence]
    relations = []

    for i, a in enumerate(objects):
        for b in objects[i + 1 :]:
            ax, ay, az = a.position_xyz
            bx, by, bz = b.position_xyz
            distance = math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)
            confidence = min(a.confidence, b.confidence)

            relations.append(
                SpatialRelation(
                    a.object_id,
                    "DISTANCE_M",
                    b.object_id,
                    distance,
                    confidence,
                    result.source,
                )
            )

            if distance <= near_threshold_m:
                relations.append(
                    SpatialRelation(
                        a.object_id,
                        "NEAR",
                        b.object_id,
                        distance,
                        confidence,
                        result.source,
                    )
                )

            if ax < bx:
                relations.append(
                    SpatialRelation(a.object_id, "LEFT_OF", b.object_id, None, confidence, result.source)
                )
            elif ax > bx:
                relations.append(
                    SpatialRelation(a.object_id, "RIGHT_OF", b.object_id, None, confidence, result.source)
                )

            if ay < by:
                relations.append(
                    SpatialRelation(a.object_id, "BELOW", b.object_id, None, confidence, result.source)
                )
            elif ay > by:
                relations.append(
                    SpatialRelation(a.object_id, "ABOVE", b.object_id, None, confidence, result.source)
                )

    return tuple(relations)


def authorize_virtual_perception(result, kill_switch, ledger):
    """
    Allow validated virtual data into simulation-only reasoning.
    Never authorizes actuator commands.
    """
    try:
        if not ledger.verify():
            return False, "AUDIT_INTEGRITY_FAILURE"

        if kill_switch.state.latched:
            return False, "KILL_SWITCH_LATCHED"

        if not result.accepted:
            return False, "PERCEPTION_REJECTED"

        if result.source not in ("SIMULATED_RENDER", "SIMULATED_SCENE_GRAPH"):
            return False, "SOURCE_NOT_ALLOWED"

        return True, "SIMULATION_DATA_ONLY"

    except Exception:
        return False, "PERCEPTION_GATE_FAILURE"
