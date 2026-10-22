from __future__ import annotations

from dataclasses import dataclass

from optimus_swarm.sensor_consistency import (
    ConsistencyPolicy,
    ConsistencyStatus,
    SensorObservation,
    evaluate_consistency,
)


@dataclass(frozen=True)
class FusedObject:
    object_id: str
    frame_id: str
    position_m: tuple[float, float, float]
    source_ids: tuple[str, ...]
    evidence_class: str = "INFERRED"


@dataclass(frozen=True)
class FusionResult:
    status: str
    objects: tuple[FusedObject, ...]
    reasons: tuple[str, ...]
    physical_execution_permitted: bool = False

    @property
    def fused_position_m(self) -> tuple[float, float, float] | None:
        if len(self.objects) != 1:
            return None
        return self.objects[0].position_m


def _weighted_position(group: list[SensorObservation]) -> tuple[float, float, float]:
    weights = [1.0 / max(item.uncertainty_sigma_m, 1e-6) ** 2 for item in group]
    total = sum(weights)
    return tuple(
        sum(weight * item.position_m[axis] for weight, item in zip(weights, group)) / total for axis in range(3)
    )


def fuse_observations(
    observations: list[SensorObservation],
    *,
    now_ms: int,
    policy: ConsistencyPolicy = ConsistencyPolicy(),
    previous_positions: dict[tuple[str, str, str], tuple[int, tuple[float, float, float]]] | None = None,
) -> FusionResult:
    """
    Fuse only a consistent same-object group.

    A conflict is not averaged. The result is an inference, not an observation,
    and it never permits physical execution.
    """
    checked = evaluate_consistency(
        observations,
        now_ms=now_ms,
        policy=policy,
        previous_positions=previous_positions,
    )
    if checked.status == ConsistencyStatus.CONFLICT:
        return FusionResult("CONFLICT_NOT_FUSED", (), checked.reasons, False)
    if checked.status != ConsistencyStatus.CONSISTENT or not checked.accepted_for_downstream:
        return FusionResult("NOT_FUSED", (), checked.reasons, False)

    groups: dict[tuple[str, str], list[SensorObservation]] = {}
    for item in observations:
        groups.setdefault((item.object_id, item.frame_id), []).append(item)

    fused: list[FusedObject] = []
    for (object_id, frame_id), group in sorted(groups.items()):
        sources = tuple(sorted({item.source_id for item in group}))
        if len(sources) < 2:
            continue
        position = _weighted_position(group)
        fused.append(FusedObject(object_id, frame_id, position, sources, "INFERRED"))

    if not fused:
        return FusionResult("NOT_FUSED", (), ("NO_FUSIBLE_GROUP",), False)
    return FusionResult("FUSED", tuple(fused), ("CONSISTENT_GROUP_FUSED",), False)
