from optimus_swarm.real_world_scenario import run_real_world_conditions


def test_real_world_conditions_stay_simulated_and_motionless():
    results = {item.name: item for item in run_real_world_conditions()}

    assert set(results) == {"nominal_pick", "human_in_cell", "occlusion_and_noise", "stale_feed"}
    assert all(item.evidence_class == "SIMULATED" for item in results.values())
    assert all(item.physical_execution_authorized is False for item in results.values())
    assert results["nominal_pick"].decision == "SIMULATION_RECORDED"
    assert results["nominal_pick"].mean_error_m is not None
    assert results["nominal_pick"].mean_error_m < 0.05
    assert results["human_in_cell"].decision == "KEEP_OUT_INHIBIT"
    assert results["stale_feed"].decision == "PERCEPTION_REJECTED"
    assert results["occlusion_and_noise"].decision == "SIMULATION_DEGRADED"
    assert "matched=0" in results["occlusion_and_noise"].detail
    assert results["occlusion_and_noise"].mean_error_m is None
    assert "OBSERVED" not in {item.evidence_class for item in results.values()}
