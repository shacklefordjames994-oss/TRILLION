from dataclasses import dataclass, asdict
import math

from optimus_swarm.rgbd_perception import RGBDResult
from optimus_swarm.synthetic_scene import GroundTruthObject


@dataclass(frozen=True)
class LocalizationMetric:
    object_id: str
    error_m: float
    estimate_xyz: tuple[float, float, float]
    ground_truth_xyz: tuple[float, float, float]


@dataclass(frozen=True)
class BenchmarkReport:
    status: str
    source: str
    matched_objects: int
    ground_truth_objects: int
    detected_objects: int
    missed_objects: int
    false_positive_objects: int
    mean_error_m: float | None
    max_error_m: float | None
    metrics: tuple[LocalizationMetric, ...]


def evaluate_localization(
    result: RGBDResult,
    ground_truth: tuple[GroundTruthObject, ...],
) -> BenchmarkReport:
    if not result.accepted:
        return BenchmarkReport(
            status="PERCEPTION_REJECTED",
            source="SIMULATION_ONLY",
            matched_objects=0,
            ground_truth_objects=len(ground_truth),
            detected_objects=0,
            missed_objects=len(ground_truth),
            false_positive_objects=0,
            mean_error_m=None,
            max_error_m=None,
            metrics=(),
        )

    truth_by_id = {obj.object_id: obj for obj in ground_truth}
    estimate_by_id = {obj.object_id: obj for obj in result.objects}

    matched_ids = sorted(set(truth_by_id) & set(estimate_by_id))
    missed = len(set(truth_by_id) - set(estimate_by_id))
    false_positives = len(set(estimate_by_id) - set(truth_by_id))

    metrics = []

    for object_id in matched_ids:
        truth = truth_by_id[object_id].position_world_xyz
        estimate = estimate_by_id[object_id].position_world_xyz
        error = math.sqrt(sum((estimate[i] - truth[i]) ** 2 for i in range(3)))
        metrics.append(
            LocalizationMetric(
                object_id=object_id,
                error_m=error,
                estimate_xyz=estimate,
                ground_truth_xyz=truth,
            )
        )

    errors = [metric.error_m for metric in metrics]

    return BenchmarkReport(
        status="EVALUATED",
        source="SIMULATION_ONLY",
        matched_objects=len(metrics),
        ground_truth_objects=len(ground_truth),
        detected_objects=len(result.objects),
        missed_objects=missed,
        false_positive_objects=false_positives,
        mean_error_m=sum(errors) / len(errors) if errors else None,
        max_error_m=max(errors) if errors else None,
        metrics=tuple(metrics),
    )


def export_simulation_report(report: BenchmarkReport, kill_switch, ledger):
    """
    Release a benchmark only as labeled simulation data.
    A failed ledger or a closed latch blocks the export.
    """
    try:
        if not ledger.verify():
            return False, "AUDIT_INTEGRITY_FAILURE"
        if kill_switch.state.latched:
            return False, "KILL_SWITCH_LATCHED"
        if report.source != "SIMULATION_ONLY":
            return False, "PROVENANCE_MISMATCH"

        payload = asdict(report)
        payload["label"] = "SIMULATION_ONLY"
        payload["physical_performance"] = False
        payload["actuator_authorized"] = False
        return True, payload
    except Exception:
        return False, "EXPORT_BLOCKED"
