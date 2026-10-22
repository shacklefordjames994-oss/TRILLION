import pytest

from optimus_swarm.kill_switch import (
    HumanAuthorityKillSwitch,
    HumanAuthorityRequired,
    InvalidSafetyTransition,
)


@pytest.fixture
def switch():
    return HumanAuthorityKillSwitch(authorized_humans={"human-001"})


def test_startup_is_inhibited(switch):
    assert switch.state.latched is True
    assert switch.permits_simulation() is False
    assert switch.permits_physical_execution() is False


def test_robot_can_inhibit(switch):
    state = switch.engage("robot-007", "Uncertain environment")

    assert state.latched is True
    assert state.changed_by == "robot-007"


def test_agent_cannot_reset(switch):
    switch.engage("robot-007", "Fault detected")

    with pytest.raises(HumanAuthorityRequired):
        switch.reset("agent-001", "approval-001", "Resume")


def test_unauthorized_human_cannot_reset(switch):
    with pytest.raises(HumanAuthorityRequired):
        switch.reset("human-999", "approval-001", "Resume")


def test_authorized_reset_clears_simulation_latch(switch):
    switch.reset("human-001", "approval-001", "Reviewed fault")

    assert switch.state.latched is False
    assert switch.permits_simulation() is True
    assert switch.permits_physical_execution() is False


def test_authorization_cannot_be_replayed(switch):
    switch.reset("human-001", "approval-001", "Reviewed fault")
    switch.engage("robot-007", "New fault")

    with pytest.raises(HumanAuthorityRequired):
        switch.reset("human-001", "approval-001", "Attempted replay")


def test_reset_does_not_work_when_already_clear(switch):
    switch.reset("human-001", "approval-001", "Reviewed fault")

    with pytest.raises(InvalidSafetyTransition):
        switch.reset("human-001", "approval-002", "Duplicate reset")


def test_revisions_increase(switch):
    first = switch.state.revision
    second = switch.engage("robot-007", "Fault")
    third = switch.reset("human-001", "approval-001", "Reviewed")

    assert second.revision > first
    assert third.revision > second.revision


def test_audit_records_inhibit_and_reset(switch):
    switch.engage("robot-007", "Fault")
    switch.reset("human-001", "approval-001", "Reviewed")

    actions = [event.action for event in switch.audit_events]

    assert actions == ["INHIBIT", "INHIBIT", "RESET"]


def test_physical_execution_never_enabled(switch):
    switch.reset("human-001", "approval-001", "Reviewed")

    assert switch.permits_physical_execution() is False
