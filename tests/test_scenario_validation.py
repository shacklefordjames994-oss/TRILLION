from optimus_swarm.scenario_validation import Scenario, calculate_metrics, run_scenario
from optimus_swarm.sensor_consistency import ConsistencyPolicy, SensorObservation


def observation(oid, source, x, captured=1000, received=1010):
    return SensorObservation(
        observation_id=oid,
        source_id=source,
        object_id="target-1",
        frame_id="world-v1",
        captured_at_ms=captured,
        received_at_ms=received,
        position_m=(x, 0.0, 0.0),
        uncertainty_sigma_m=0.05,
    )


def make_scenarios():
    return [
        Scenario(
            "consistent-01",
            (observation("a1", "camera", 1.0), observation("b1", "depth", 1.1)),
            now_ms=1020,
            expected_conflict=False,
        ),
        Scenario(
            "conflict-01",
            (observation("a2", "camera", 1.0), observation("b2", "depth", 2.0)),
            now_ms=1020,
            expected_conflict=True,
            injected_at_ms=1000,
        ),
        Scenario(
            "stale-01",
            (observation("a3", "camera", 1.0, captured=100, received=110),),
            now_ms=2000,
            expected_conflict=False,
            expected_stale=True,
        ),
    ]


def test_scenarios_block_expected_conflict_and_stale_data():
    scenarios = make_scenarios()
    results = [run_scenario(scenario) for scenario in scenarios]
    by_id = {result.scenario_id: result for result in results}

    assert by_id["consistent-01"].accepted_for_downstream
    assert not by_id["conflict-01"].accepted_for_downstream
    assert by_id["conflict-01"].detected_conflict
    assert by_id["conflict-01"].detection_latency_ms == 20
    assert not by_id["stale-01"].accepted_for_downstream
    assert all(result.physical_execution_permitted is False for result in results)


def test_metrics_calculation():
    scenarios = make_scenarios()
    results = [run_scenario(scenario) for scenario in scenarios]
    metrics = calculate_metrics(scenarios, results, repeatability_pass=True)

    assert metrics.true_positive == 1
    assert metrics.false_negative == 0
    assert metrics.false_positive == 0
    assert metrics.true_negative == 2
    assert metrics.conflict_recall == 1.0
    assert metrics.missed_conflict_rate == 0.0
    assert metrics.false_alarm_rate == 0.0
    assert metrics.stale_rejections == 1
    assert metrics.stale_cases == 1
    assert metrics.fail_closed_violations == 0


def test_repeatability_for_identical_scenarios():
    scenarios = make_scenarios()
    first = [run_scenario(scenario) for scenario in scenarios]
    second = [run_scenario(scenario) for scenario in scenarios]
    assert first == second


def test_invalid_scenario_policy_fails_closed():
    scenarios = make_scenarios()
    result = run_scenario(scenarios[0], policy=ConsistencyPolicy(conflict_distance_m=float("nan")))

    assert not result.accepted_for_downstream
    assert result.status == "INVALID"
    assert result.physical_execution_permitted is False
