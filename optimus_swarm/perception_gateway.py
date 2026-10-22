from dataclasses import dataclass


@dataclass(frozen=True)
class PerceptionEnvelope:
    robot_id: str
    frame_id: str
    scene_id: str
    timestamp_ms: int
    source: str
    coordinate_frame: str
    object_count: int
    status: str


@dataclass(frozen=True)
class PathOption:
    path_id: str
    clearance_m: float
    uncertainty_m: float


class PerceptionGateway:
    def __init__(self, kill_switch, ledger):
        self.kill_switch = kill_switch
        self.ledger = ledger

    def authorize(self, result, robot_id: str, scene_id: str):
        try:
            if not self.ledger.verify():
                return False, "AUDIT_INTEGRITY_FAILURE"

            if self.kill_switch.state.latched:
                return False, "KILL_SWITCH_LATCHED"

            if not result.accepted:
                return False, "PERCEPTION_REJECTED"

            if result.code != "RGBD_PERCEPTION_ACCEPTED":
                return False, "UNEXPECTED_RESULT_TYPE"

            if not robot_id or not scene_id or not result.frame_id:
                return False, "INVALID_ENVELOPE"

            for obj in result.objects:
                if obj.provenance != "SIMULATED_RENDER":
                    return False, "PROVENANCE_MISMATCH"

            envelope = PerceptionEnvelope(
                robot_id=robot_id,
                frame_id=result.frame_id,
                scene_id=scene_id,
                timestamp_ms=0,
                source="SIMULATED_RENDER",
                coordinate_frame="world",
                object_count=len(result.objects),
                status="SIMULATION_ONLY",
            )

            self.ledger.append(
                actor_id=robot_id,
                event_type="VIRTUAL_PERCEPTION_ACCEPTED",
                reason=(
                    f"frame={envelope.frame_id}; "
                    f"scene={envelope.scene_id}; "
                    f"objects={envelope.object_count}"
                ),
            )

            return True, envelope

        except Exception:
            return False, "PERCEPTION_GATE_FAILURE"


def compare_simulated_paths(
    options: tuple[PathOption, ...],
    min_clearance_m: float = 0.15,
) -> tuple[bool, dict]:
    """
    Compare simulated path alternatives.
    A preferred id is not an actuator command.
    """
    try:
        if not options:
            return False, {"code": "NO_OPTIONS", "actuator": False}
        if min_clearance_m <= 0:
            return False, {"code": "INVALID_CLEARANCE", "actuator": False}

        ranked = sorted(options, key=lambda option: (-option.clearance_m, option.uncertainty_m))
        preferred = ranked[0]
        needs_human = any(option.clearance_m < min_clearance_m for option in options)
        return True, {
            "code": "SIMULATED_COMPARISON",
            "preferred": preferred.path_id,
            "human_review": needs_human,
            "actuator": False,
        }
    except Exception:
        return False, {"code": "COMPARISON_FAILURE", "actuator": False}
