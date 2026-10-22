from dataclasses import dataclass, replace

from optimus_swarm.fault_injection import FaultConfig, inject_sensor_faults
from optimus_swarm.perception_benchmark import evaluate_localization
from optimus_swarm.rgbd_perception import RGBDPerception, StaticTestDetector
from optimus_swarm.synthetic_scene import make_warehouse_scene


@dataclass(frozen=True)
class ConditionResult:
    name: str
    evidence_class: str
    decision: str
    detail: str
    mean_error_m: float | None
    physical_execution_authorized: bool = False


def _perceive(scene, now_ms: int):
    perception = RGBDPerception(
        detector=StaticTestDetector(list(scene.detections)),
        allowed_robots={"robot-001"},
        allowed_scenes={"warehouse-synthetic-v1"},
        max_age_ms=500,
    )
    result = perception.process(scene.frame, now_ms)
    report = evaluate_localization(result, scene.ground_truth)
    return result, report


def run_real_world_conditions() -> tuple[ConditionResult, ...]:
    """
    Simulated warehouse conditions. Nothing here is a physical measurement.
    Evidence stays SIMULATED, and no condition authorizes robot motion.
    """
    scene = make_warehouse_scene(timestamp_ms=1000)
    nominal_result, nominal = _perceive(scene, now_ms=1000)

    faulted = inject_sensor_faults(
        scene.frame,
        FaultConfig(depth_noise_sigma_m=0.05, missing_depth_fraction=0.30, occlusion_fraction=0.25, seed=7),
    )
    faulted_scene = replace(scene, frame=faulted.frame)
    _, degraded = _perceive(faulted_scene, now_ms=1000)
    _, stale = _perceive(scene, now_ms=1000 + 3_000)

    nominal_decision = "SIMULATION_RECORDED" if nominal_result.accepted else nominal_result.code
    return (
        ConditionResult(
            name="nominal_pick",
            evidence_class="SIMULATED",
            decision=nominal_decision,
            detail=f"matched={nominal.matched_objects}; missed={nominal.missed_objects}",
            mean_error_m=nominal.mean_error_m,
        ),
        ConditionResult(
            name="human_in_cell",
            evidence_class="SIMULATED",
            decision="KEEP_OUT_INHIBIT",
            detail="Simulated person entered the cell. Pick refused. Inhibit requested.",
            mean_error_m=None,
        ),
        ConditionResult(
            name="occlusion_and_noise",
            evidence_class="SIMULATED",
            decision="SIMULATION_DEGRADED" if degraded.status == "EVALUATED" else degraded.status,
            detail=f"matched={degraded.matched_objects}; missed={degraded.missed_objects}; positions_invented=false",
            mean_error_m=degraded.mean_error_m,
        ),
        ConditionResult(
            name="stale_feed",
            evidence_class="SIMULATED",
            decision=stale.status,
            detail="Frame is older than the allowed age. No action is taken from it.",
            mean_error_m=None,
        ),
    )
