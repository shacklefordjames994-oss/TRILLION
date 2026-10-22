from dataclasses import dataclass
import math

from optimus_swarm.rgbd_perception import Object3D, RGBDResult


@dataclass(frozen=True)
class TrackedObject:
    object_id: str
    class_name: str
    position_xyz: tuple[float, float, float]
    velocity_xyz_mps: tuple[float, float, float] | None
    confidence: float
    provenance: str
    timestamp_ms: int


class VirtualObjectTracker:
    """
    Simulation-only tracker.

    Uses stable simulator object IDs. It is not a general-purpose
    visual multi-object tracker and does not handle ID switches.
    """

    def __init__(self, max_interval_ms: int = 1000):
        if max_interval_ms <= 0:
            raise ValueError("max_interval_ms must be positive")
        self.max_interval_ms = max_interval_ms
        self._previous: dict[str, TrackedObject] = {}

    def update(self, result: RGBDResult, timestamp_ms: int) -> tuple[TrackedObject, ...]:
        if not result.accepted:
            return ()

        if result.code != "RGBD_PERCEPTION_ACCEPTED":
            return ()

        if timestamp_ms < 0:
            return ()

        current = {}
        output = []

        for obj in result.objects:
            previous = self._previous.get(obj.object_id)
            velocity = None

            if previous is not None:
                dt_ms = timestamp_ms - previous.timestamp_ms

                if 0 < dt_ms <= self.max_interval_ms:
                    dt = dt_ms / 1000.0
                    velocity = tuple(
                        (new - old) / dt
                        for new, old in zip(obj.position_world_xyz, previous.position_xyz)
                    )

                    if not all(math.isfinite(v) for v in velocity):
                        velocity = None

            tracked = TrackedObject(
                object_id=obj.object_id,
                class_name=obj.class_name,
                position_xyz=obj.position_world_xyz,
                velocity_xyz_mps=velocity,
                confidence=obj.confidence,
                provenance=obj.provenance,
                timestamp_ms=timestamp_ms,
            )
            current[obj.object_id] = tracked
            output.append(tracked)

        # Replace the active track set. Missing objects are not assumed
        # to be destroyed; they may be occluded or outside the camera view.
        self._previous = current
        return tuple(output)
