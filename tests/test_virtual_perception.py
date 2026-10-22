from dataclasses import replace

from optimus_swarm.hardware_interlock import HardwareSafetyChain
from optimus_swarm.integrity import TamperEvidentLedger
from optimus_swarm.kill_switch import HumanAuthorityKillSwitch
from optimus_swarm.virtual_perception import (
    VirtualFrame,
    VirtualObject,
    VirtualPerception,
    authorize_virtual_perception,
    derive_spatial_relations,
)


def make_perceptor():
    return VirtualPerception(
        allowed_robots={"robot-001"},
        allowed_scenes={"warehouse-sim-v1"},
        max_frame_age_ms=1000,
    )


def make_frame(timestamp=1000):
    return VirtualFrame(
        frame_id="frame-001",
        robot_id="robot-001",
        scene_id="warehouse-sim-v1",
        timestamp_ms=timestamp,
        coordinate_frame="world",
        source="SIMULATED_SCENE_GRAPH",
        objects=(
            VirtualObject("box-1", "box", (0.0, 0.0, 0.0), 0.98),
            VirtualObject("table-1", "table", (0.5, 0.0, 0.0), 0.95),
        ),
    )


def test_accepts_valid_virtual_scene():
    result = make_perceptor().perceive(make_frame(), now_ms=1100)

    assert result.accepted
    assert result.source == "SIMULATED_SCENE_GRAPH"
    assert len(result.objects) == 2


def test_rejects_unknown_robot():
    frame = make_frame()
    frame = VirtualFrame(**{**frame.__dict__, "robot_id": "unknown-robot"})

    result = make_perceptor().perceive(frame, now_ms=1100)
    assert not result.accepted
    assert result.code == "ROBOT_NOT_ALLOWED"


def test_rejects_stale_frame():
    result = make_perceptor().perceive(make_frame(1000), now_ms=2500)

    assert not result.accepted
    assert result.code == "STALE_FRAME"


def test_rejects_future_frame():
    result = make_perceptor().perceive(make_frame(2000), now_ms=1100)

    assert not result.accepted
    assert result.code == "FUTURE_FRAME"


def test_derives_near_relation():
    result = make_perceptor().perceive(make_frame(), now_ms=1100)
    relations = derive_spatial_relations(result, near_threshold_m=1.0)

    assert any(
        r.subject_id == "box-1" and r.relation == "NEAR" and r.target_id == "table-1" for r in relations
    )


def test_rejected_frame_produces_no_relations():
    result = make_perceptor().perceive(make_frame(), now_ms=3000)

    assert not result.accepted
    assert derive_spatial_relations(result) == ()


def test_physical_observation_is_not_inferred():
    result = make_perceptor().perceive(make_frame(), now_ms=1100)

    assert result.accepted
    assert all(obj.provenance == "SIMULATED_SCENE_GRAPH" for obj in result.objects)


def test_latched_switch_blocks_planner_use():
    result = make_perceptor().perceive(make_frame(), now_ms=1100)
    switch = HumanAuthorityKillSwitch({"human-001"})
    ledger = TamperEvidentLedger(b"p" * 32)

    allowed, code = authorize_virtual_perception(result, switch, ledger)

    assert result.accepted
    assert not allowed
    assert code == "KILL_SWITCH_LATCHED"


def test_broken_ledger_blocks_perception():
    ledger = TamperEvidentLedger(b"p" * 32)
    record = ledger.append("robot-001", "NOTE", "seed")
    ledger._records[0] = replace(record, reason="Altered")
    switch = HumanAuthorityKillSwitch({"human-001"})
    switch.reset("human-001", "approval-p", "simulation review")
    result = make_perceptor().perceive(make_frame(), now_ms=1100)

    allowed, code = authorize_virtual_perception(result, switch, ledger)

    assert not allowed
    assert code == "AUDIT_INTEGRITY_FAILURE"


def test_perception_gate_does_not_enable_actuators():
    switch = HumanAuthorityKillSwitch({"human-001"})
    switch.reset("human-001", "approval-p", "simulation review")
    ledger = TamperEvidentLedger(b"p" * 32)
    result = make_perceptor().perceive(make_frame(), now_ms=1100)

    allowed, code = authorize_virtual_perception(result, switch, ledger)

    assert allowed
    assert code == "SIMULATION_DATA_ONLY"
    assert HardwareSafetyChain({"human-001"}).actuator_command("use-perception") == (
        False,
        "NO_SAFETY_RATED_OUTPUT",
    )
