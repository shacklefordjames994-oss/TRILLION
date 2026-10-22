import pytest

from optimus_swarm.integration_adapter import SimulationAdapter
from optimus_swarm.integration_models import PipelineStatus
from optimus_swarm.integration_pipeline import OmegaSimulationPipeline
from optimus_swarm.secure_command_models import CommandDecision, DecisionStatus


class FakeGateway:
    def __init__(self, decision):
        self.decision = decision

    def authorize_simulation(self, command, *, now_ms):
        return self.decision


class FakeCommand:
    command_id = "cmd-001"
    payload = {"operation": "simulate_navigation"}


def test_accepted_command_records_simulation_event():
    decision = CommandDecision(
        status=DecisionStatus.ACCEPTED,
        code="SIMULATION_ADMISSION_ACCEPTED",
        command_id="cmd-001",
        simulation_permitted=True,
        physical_execution_authorized=False,
    )
    pipeline = OmegaSimulationPipeline(gateway=FakeGateway(decision), adapter=SimulationAdapter())
    result = pipeline.process(FakeCommand(), now_ms=2000)

    assert result.status == PipelineStatus.ACCEPTED
    assert result.simulation_event_recorded is True
    assert result.physical_execution_authorized is False


def test_rejected_command_never_reaches_adapter():
    decision = CommandDecision(
        status=DecisionStatus.REJECTED,
        code="INHIBIT_LATCHED",
        command_id="cmd-001",
        simulation_permitted=False,
        physical_execution_authorized=False,
    )
    adapter = SimulationAdapter()
    pipeline = OmegaSimulationPipeline(gateway=FakeGateway(decision), adapter=adapter)
    result = pipeline.process(FakeCommand(), now_ms=2000)

    assert result.status == PipelineStatus.REJECTED
    assert result.stage == "SECURITY_GATEWAY"
    assert adapter.events() == ()


def test_indeterminate_gateway_result_fails_closed():
    decision = CommandDecision(
        status=DecisionStatus.INDETERMINATE,
        code="SECURITY_DEPENDENCY_FAILURE",
        command_id="cmd-001",
        simulation_permitted=False,
        physical_execution_authorized=False,
    )
    pipeline = OmegaSimulationPipeline(gateway=FakeGateway(decision), adapter=SimulationAdapter())
    result = pipeline.process(FakeCommand(), now_ms=2000)

    assert result.status == PipelineStatus.INDETERMINATE
    assert result.simulation_event_recorded is False


def test_invalid_operation_is_rejected_before_gateway():
    class CountingGateway(FakeGateway):
        def __init__(self):
            self.calls = 0

        def authorize_simulation(self, command, *, now_ms):
            self.calls += 1
            raise AssertionError("schema failure must not reach the gateway")

    class BadCommand:
        command_id = "cmd-bad"
        payload = {"operation": "enable_actuators"}

    gateway = CountingGateway()
    pipeline = OmegaSimulationPipeline(gateway=gateway, adapter=SimulationAdapter())
    result = pipeline.process(BadCommand(), now_ms=2000)

    assert result.status == PipelineStatus.REJECTED
    assert result.stage == "SCHEMA"
    assert result.reason == "INVALID_OPERATION"
    assert gateway.calls == 0
    assert result.physical_execution_authorized is False


def test_adapter_rejects_physical_authorization():
    adapter = SimulationAdapter()
    decision = CommandDecision(
        status=DecisionStatus.ACCEPTED,
        code="INVALID_PHYSICAL_AUTHORIZATION",
        command_id="cmd-002",
        simulation_permitted=True,
        physical_execution_authorized=True,
    )
    with pytest.raises(PermissionError):
        adapter.record(
            decision=decision,
            operation="simulate_navigation",
            payload_digest="a" * 64,
            now_ms=2000,
        )


def test_duplicate_simulation_event_is_rejected():
    adapter = SimulationAdapter()
    decision = CommandDecision(
        status=DecisionStatus.ACCEPTED,
        code="SIMULATION_ADMISSION_ACCEPTED",
        command_id="cmd-003",
        simulation_permitted=True,
        physical_execution_authorized=False,
    )
    args = {
        "decision": decision,
        "operation": "simulate_navigation",
        "payload_digest": "b" * 64,
        "now_ms": 2000,
    }
    adapter.record(**args)
    with pytest.raises(ValueError, match="DUPLICATE_SIMULATION_EVENT"):
        adapter.record(**args)
