from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from optimus_swarm.benchmark_journal import AssessmentStatus, BenchmarkJournal
from optimus_swarm.hardware_interlock import HardwareSafetyChain, HardwareStopRequired
from optimus_swarm.independent_gate import GateStatus, ScenarioRecord, assess_benchmark, scenario_set_digest
from optimus_swarm.kill_switch import HumanAuthorityKillSwitch

REQUIRED = ("clear-01", "conflict-01", "stale-01")
POLICY = "a" * 64


@dataclass(frozen=True)
class HardwareCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class HardwareVerificationReport:
    status: str
    checks: tuple[HardwareCheck, ...]
    actuator_output_enabled: bool = False
    certification_claimed: bool = False
    physical_execution_permitted: bool = False
    limitations: tuple[str, ...] = (
        "Software model of a series safety chain",
        "Not a safety-rated relay, contactor, or emergency stop",
        "Not an ISO 13849 or IEC 62061 certificate",
        "Actuator output is forced off in this model",
    )


def _passing_gate():
    scenarios = tuple(
        ScenarioRecord(scenario_id, "PASS", True, str(index + 1) * 64) for index, scenario_id in enumerate(REQUIRED)
    )
    return assess_benchmark(
        run_id="run-hw-001",
        policy_digest=POLICY,
        expected_policy_digest=POLICY,
        required_scenario_ids=REQUIRED,
        declared_scenario_set_digest=scenario_set_digest(REQUIRED),
        scenarios=scenarios,
        physical_execution_enabled=False,
    )


def _close_chain(chain: HardwareSafetyChain):
    chain.release_estop("human-001")
    chain.pulse("safety-plc", 100)
    chain.hardware_reset("human-001", "channel-verify", "contacts checked in the model", 100)
    return chain.report_feedback(True, 120)


def verify_hardware_model(journal_path: str | Path) -> HardwareVerificationReport:
    """Run the software model. A passing report is not a hardware certificate."""
    checks: list[HardwareCheck] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append(HardwareCheck(name, passed, detail))

    boot = HardwareSafetyChain({"human-001"})
    boot_status = boot.evaluate(0)
    add(
        "chain boots open",
        boot_status.motion_power is False and boot_status.actuator_output_enabled is False and boot_status.estop_loop_closed is False,
        boot_status.reason,
    )

    gate = _passing_gate()
    allowed, code = boot.actuator_command("joint_torque")
    add(
        "benchmark pass does not enable an actuator",
        gate.status == GateStatus.PASS and allowed is False and code == "NO_SAFETY_RATED_OUTPUT",
        code,
    )

    switch = HumanAuthorityKillSwitch({"human-001"})
    switch.reset("human-001", "approval-hw", "Simulation latch only")
    allowed, code = boot.actuator_command("joint_torque")
    add(
        "simulation reset leaves the hardware chain open",
        switch.permits_simulation() is True
        and switch.permits_physical_execution() is False
        and boot.evaluate(0).estop_loop_closed is False
        and allowed is False,
        code,
    )

    closed = HardwareSafetyChain({"human-001"}, watchdog_ms=250)
    closed_status = _close_chain(closed)
    allowed, code = closed.actuator_command("joint_torque")
    add(
        "closed model still disables actuator output",
        closed_status.motion_power is True and closed_status.actuator_output_enabled is False and allowed is False,
        closed_status.reason,
    )

    expired = closed.evaluate(1000)
    add(
        "stale watchdog opens the chain",
        expired.watchdog_closed is False and expired.motion_power is False and expired.actuator_output_enabled is False,
        expired.reason,
    )

    guarded = HardwareSafetyChain({"human-001"})
    guarded.open_guard("person in the cell")
    robot_blocked = False
    try:
        guarded.hardware_reset("robot-007", "channel-robot", "attempt", 0)
    except HardwareStopRequired:
        robot_blocked = True
    guarded_status = guarded.evaluate(0)
    add(
        "robot cannot reset an open guard",
        robot_blocked and guarded_status.guard_closed is False and guarded_status.motion_power is False,
        guarded_status.reason,
    )

    disagree = HardwareSafetyChain({"human-001"})
    fault = disagree.report_feedback(True, 0)
    add(
        "feedback while open latches a fault",
        fault.fault_latched is True and fault.motion_power is False and fault.actuator_output_enabled is False,
        fault.reason,
    )

    journal = BenchmarkJournal(journal_path)
    journal.store_run(
        "run-hw-001",
        {
            "run_id": "run-hw-001",
            "policy_digest": POLICY,
            "status": "PASS",
            "physical_execution_enabled": False,
        },
        "2026-10-22T12:00:00Z",
    )
    stored = journal.append_assessment(
        "assessment-hw-001",
        "run-hw-001",
        journal.read_run("run-hw-001").payload_digest,
        AssessmentStatus.PASS,
        ("Software checks only",),
    )
    add(
        "stored assessment cannot command an actuator",
        stored.physical_execution_enabled is False and boot.actuator_command("joint_torque")[0] is False,
        "PHYSICAL_EXECUTION_INHIBITED",
    )

    actuator_ever_enabled = any(check.detail == "ACTUATOR_ENABLED" for check in checks)
    status = "MODEL_CHECKED" if all(check.passed for check in checks) and not actuator_ever_enabled else "FAIL"
    return HardwareVerificationReport(status, tuple(checks), False, False, False)
