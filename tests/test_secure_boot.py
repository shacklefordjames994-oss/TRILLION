from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from optimus_swarm.kill_switch import HumanAuthorityKillSwitch
from optimus_swarm.secure_boot import SecureBootChain, root_measurement, sign_stage


def chain(tmp_path, version=1):
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    previous = root_measurement(public)
    images = {}
    stages = []
    for name in ("BOOTLOADER", "POLICY", "APPLICATION"):
        image = f"{name}-v{version}".encode()
        stage = sign_stage(private, name=name, version=version, image=image, previous_sha256=previous)
        images[name] = image
        stages.append(stage)
        previous = stage.image_sha256
    return SecureBootChain(public, tmp_path / "boot.db"), stages, images


def test_verified_chain_is_simulation_only(tmp_path):
    boot, stages, images = chain(tmp_path)
    switch = HumanAuthorityKillSwitch({"human-001"})
    decision = boot.boot(stages, images, kill_switch=switch)

    assert decision.status == "VERIFIED"
    assert decision.simulation_ready is True
    assert decision.stage_reached == "APPLICATION"
    assert decision.physical_execution_permitted is False
    assert decision.inhibit_cleared is False
    assert switch.state.latched is True
    assert switch.permits_physical_execution() is False


def test_tampered_image_stops_the_chain(tmp_path):
    boot, stages, images = chain(tmp_path)
    images["APPLICATION"] = b"tampered-application"
    decision = boot.boot(stages, images)

    assert decision.status == "DENIED"
    assert decision.simulation_ready is False
    assert decision.stage_reached == "POLICY"
    assert "APPLICATION: image measurement mismatch" in decision.reasons
    assert decision.physical_execution_permitted is False


def test_restart_rejects_an_older_stage(tmp_path):
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    path = tmp_path / "boot.db"

    def build(version: int):
        previous = root_measurement(public)
        images = {}
        stages = []
        for name in ("BOOTLOADER", "POLICY", "APPLICATION"):
            image = f"{name}-v{version}".encode()
            stage = sign_stage(private, name=name, version=version, image=image, previous_sha256=previous)
            images[name] = image
            stages.append(stage)
            previous = stage.image_sha256
        return stages, images

    assert SecureBootChain(public, path).boot(*build(2)).status == "VERIFIED"
    decision = SecureBootChain(public, path).boot(*build(1))

    assert decision.status == "DENIED"
    assert decision.simulation_ready is False
    assert any("rollback rejected" in reason for reason in decision.reasons)
    assert decision.physical_execution_permitted is False


def test_incomplete_chain_is_denied(tmp_path):
    boot, stages, images = chain(tmp_path)
    decision = boot.boot(stages[:2], images)

    assert decision.status == "DENIED"
    assert decision.simulation_ready is False
    assert decision.reasons == ("Boot chain is incomplete",)


def test_bad_signature_is_denied(tmp_path):
    boot, stages, images = chain(tmp_path)
    forged = stages[2]
    stages[2] = type(forged)(
        forged.name,
        forged.version,
        forged.image_sha256,
        forged.previous_sha256,
        "AA",
    )
    decision = boot.boot(stages, images)

    assert decision.status == "DENIED"
    assert decision.simulation_ready is False
    assert "APPLICATION: signature rejected" in decision.reasons
