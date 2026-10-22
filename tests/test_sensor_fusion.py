import math

from optimus_swarm.sensor_consistency import SensorObservation
from optimus_swarm.sensor_fusion import fuse_observations


def obs(oid, source, x, sigma=0.05):
    return SensorObservation(
        observation_id=oid,
        source_id=source,
        object_id="person-1",
        frame_id="world-v1",
        captured_at_ms=1000,
        received_at_ms=1010,
        position_m=(x, 0.0, 0.0),
        uncertainty_sigma_m=sigma,
    )


def test_conflicting_sensor_data_is_not_fused():
    result = fuse_observations([obs("a", "camera-a", 1.0), obs("b", "depth-b", 3.0)], now_ms=1020)

    assert result.status == "CONFLICT_NOT_FUSED"
    assert result.fused_position_m is None
    assert result.objects == ()
    assert any("SENSOR_DISAGREEMENT" in reason for reason in result.reasons)
    assert result.physical_execution_permitted is False


def test_agreeing_sensors_fuse_without_becoming_an_observation():
    result = fuse_observations(
        [obs("a", "camera-a", 1.0, sigma=0.10), obs("b", "depth-b", 1.2, sigma=0.10)],
        now_ms=1020,
    )

    assert result.status == "FUSED"
    assert result.fused_position_m is not None
    assert math.isclose(result.fused_position_m[0], 1.1)
    assert result.objects[0].evidence_class == "INFERRED"
    assert result.objects[0].source_ids == ("camera-a", "depth-b")
    assert result.physical_execution_permitted is False


def test_moving_object_fuses_only_when_the_motion_is_plausible():
    previous = {
        ("camera-a", "person-1", "world-v1"): (1000, (0.0, 0.0, 0.0)),
        ("depth-b", "person-1", "world-v1"): (1000, (0.05, 0.0, 0.0)),
    }
    moved = [
        SensorObservation(
            "camera-now",
            "camera-a",
            "person-1",
            "world-v1",
            1100,
            1110,
            (0.40, 0.0, 0.0),
            0.05,
        ),
        SensorObservation(
            "depth-now",
            "depth-b",
            "person-1",
            "world-v1",
            1100,
            1110,
            (0.45, 0.0, 0.0),
            0.05,
        ),
    ]
    result = fuse_observations(moved, now_ms=1120, previous_positions=previous)

    assert result.status == "FUSED"
    assert result.fused_position_m is not None
    assert math.isclose(result.fused_position_m[0], 0.425)
    assert result.objects[0].evidence_class == "INFERRED"
    assert result.physical_execution_permitted is False

    jumped = [
        SensorObservation(
            "camera-jump",
            "camera-a",
            "person-1",
            "world-v1",
            1100,
            1110,
            (10.0, 0.0, 0.0),
            0.05,
        ),
        SensorObservation(
            "depth-jump",
            "depth-b",
            "person-1",
            "world-v1",
            1100,
            1110,
            (10.1, 0.0, 0.0),
            0.05,
        ),
    ]
    rejected = fuse_observations(jumped, now_ms=1120, previous_positions=previous)
    assert rejected.status == "NOT_FUSED"
    assert rejected.fused_position_m is None
    assert any("IMPLAUSIBLE_IMPLIED_SPEED" in reason for reason in rejected.reasons)
    assert rejected.physical_execution_permitted is False
