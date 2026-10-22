from dataclasses import dataclass

from optimus_swarm.kill_switch import HumanAuthorityKillSwitch
from optimus_swarm.task_admission_gate import admit_simulated_task
from optimus_swarm.task_models import TaskLease


@dataclass
class Latch:
    latched: bool


def lease() -> TaskLease:
    return TaskLease(
        lease_id="lease-1",
        task_id="task-001",
        worker_id="robot-001",
        issued_at_ms=1000,
        expires_at_ms=2000,
        generation=1,
    )


def test_latched_switch_blocks_admission():
    decision = admit_simulated_task(
        lease(),
        worker_id="robot-001",
        now_ms=1500,
        kill_switch=type("Switch", (), {"state": Latch(True)})(),
        integrity_verified=True,
    )

    assert not decision.accepted
    assert decision.reason == "SAFETY_INHIBIT_ACTIVE"
    assert decision.physical_execution_authorized is False


def test_clear_latch_admits_simulation_only():
    decision = admit_simulated_task(
        lease(),
        worker_id="robot-001",
        now_ms=1500,
        kill_switch=type("Switch", (), {"state": Latch(False)})(),
        integrity_verified=True,
    )

    assert decision.accepted
    assert decision.reason == "SIMULATED_TASK_ADMITTED"
    assert decision.physical_execution_authorized is False


def test_missing_integrity_and_expired_lease_are_rejected():
    unverified = admit_simulated_task(
        lease(),
        worker_id="robot-001",
        now_ms=1500,
        kill_switch=type("Switch", (), {"state": Latch(False)})(),
        integrity_verified=False,
    )
    expired = admit_simulated_task(
        lease(),
        worker_id="robot-001",
        now_ms=2000,
        kill_switch=type("Switch", (), {"state": Latch(False)})(),
        integrity_verified=True,
    )

    assert unverified.reason == "INTEGRITY_NOT_VERIFIED"
    assert expired.reason == "LEASE_EXPIRED"


def test_real_kill_switch_reset_does_not_authorize_motion():
    switch = HumanAuthorityKillSwitch({"human-001"})
    blocked = admit_simulated_task(
        lease(),
        worker_id="robot-001",
        now_ms=1500,
        kill_switch=switch,
        integrity_verified=True,
    )
    switch.reset("human-001", "approval-task", "Reviewed. This does not resume hardware.")
    admitted = admit_simulated_task(
        lease(),
        worker_id="robot-001",
        now_ms=1500,
        kill_switch=switch,
        integrity_verified=True,
    )

    assert blocked.reason == "SAFETY_INHIBIT_ACTIVE"
    assert admitted.accepted
    assert admitted.physical_execution_authorized is False
