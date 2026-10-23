from optimus_swarm.hardware_verification import verify_hardware_model


def test_hardware_model_checks_pass_without_certifying_motion(tmp_path):
    report = verify_hardware_model(tmp_path / "hardware.sqlite")

    assert report.status == "MODEL_CHECKED"
    assert report.checks
    assert all(check.passed for check in report.checks)
    assert report.actuator_output_enabled is False
    assert report.certification_claimed is False
    assert report.physical_execution_permitted is False
    assert any("ISO 13849" in item for item in report.limitations)


def test_each_hardware_check_is_named(tmp_path):
    report = verify_hardware_model(tmp_path / "hardware.sqlite")
    names = {check.name for check in report.checks}

    assert "chain boots open" in names
    assert "benchmark pass does not enable an actuator" in names
    assert "closed model still disables actuator output" in names
    assert "stale watchdog opens the chain" in names
    assert "robot cannot reset an open guard" in names
    assert "feedback while open latches a fault" in names
