from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

BOOT_ORDER = ("BOOTLOADER", "POLICY", "APPLICATION")


def _canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def root_measurement(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    return _sha256(raw)


@dataclass(frozen=True)
class BootStage:
    name: str
    version: int
    image_sha256: str
    previous_sha256: str
    signature_b64: str


@dataclass(frozen=True)
class BootDecision:
    status: str
    simulation_ready: bool
    stage_reached: str
    reasons: tuple[str, ...]
    inhibit_cleared: bool = False
    physical_execution_permitted: bool = False


def sign_stage(
    private_key: Ed25519PrivateKey,
    *,
    name: str,
    version: int,
    image: bytes,
    previous_sha256: str,
) -> BootStage:
    if name not in BOOT_ORDER:
        raise ValueError("Unknown boot stage")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("Boot version must be a positive integer")
    if not isinstance(image, bytes) or not image:
        raise ValueError("Boot image is required")
    if len(previous_sha256) != 64:
        raise ValueError("Previous measurement is required")
    image_sha256 = _sha256(image)
    payload = {
        "name": name,
        "version": version,
        "image_sha256": image_sha256,
        "previous_sha256": previous_sha256,
        "mode": "SIMULATION_ONLY",
    }
    signature = base64.b64encode(private_key.sign(_canonical(payload))).decode("ascii")
    return BootStage(name, version, image_sha256, previous_sha256, signature)


class SecureBootChain:
    """
    Software model of a measured boot chain.

    The trusted public key is supplied by the caller. This object is not a
    hardware root of trust, and a verified chain does not enable actuators.
    """

    def __init__(self, public_key: Ed25519PublicKey, database_path: str | Path):
        self._public_key = public_key
        self._path = str(database_path)
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS boot_versions (
                    stage_name TEXT PRIMARY KEY,
                    version INTEGER NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=5.0)
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def boot(self, stages: list[BootStage], images: dict[str, bytes], *, kill_switch=None) -> BootDecision:
        revision = None if kill_switch is None else kill_switch.state.revision
        latched = None if kill_switch is None else kill_switch.state.latched
        try:
            decision = self._boot(stages, images)
        except sqlite3.Error:
            decision = BootDecision("INDETERMINATE", False, "ROOT", ("Boot version store unavailable",))
        if kill_switch is not None:
            state = kill_switch.state
            if state.revision != revision or state.latched != latched or kill_switch.permits_physical_execution():
                return BootDecision("FAIL", False, decision.stage_reached, decision.reasons + ("Inhibit changed during boot",), True, False)
        return decision

    def _boot(self, stages: list[BootStage], images: dict[str, bytes]) -> BootDecision:
        by_name = {stage.name: stage for stage in stages}
        if len(by_name) != len(stages) or tuple(by_name) != BOOT_ORDER and set(by_name) != set(BOOT_ORDER):
            if len(by_name) != len(stages) or set(by_name) != set(BOOT_ORDER):
                return BootDecision("DENIED", False, "ROOT", ("Boot chain is incomplete",))
        ordered = [by_name[name] for name in BOOT_ORDER]
        previous = root_measurement(self._public_key)
        reached = "ROOT"

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            stored = {name: version for name, version in db.execute("SELECT stage_name, version FROM boot_versions")}
            for stage in ordered:
                image = images.get(stage.name)
                if not isinstance(image, bytes) or not image:
                    return BootDecision("DENIED", False, reached, (f"{stage.name}: image missing",))
                if stage.previous_sha256 != previous:
                    return BootDecision("DENIED", False, reached, (f"{stage.name}: measurement chain break",))
                if _sha256(image) != stage.image_sha256:
                    return BootDecision("DENIED", False, reached, (f"{stage.name}: image measurement mismatch",))
                payload = {
                    "name": stage.name,
                    "version": stage.version,
                    "image_sha256": stage.image_sha256,
                    "previous_sha256": stage.previous_sha256,
                    "mode": "SIMULATION_ONLY",
                }
                try:
                    self._public_key.verify(base64.b64decode(stage.signature_b64), _canonical(payload))
                except (InvalidSignature, ValueError):
                    return BootDecision("DENIED", False, reached, (f"{stage.name}: signature rejected",))
                accepted = stored.get(stage.name, 0)
                if stage.version < accepted:
                    return BootDecision("DENIED", False, reached, (f"{stage.name}: rollback rejected",))
                previous = stage.image_sha256
                reached = stage.name
            for stage in ordered:
                db.execute(
                    """
                    INSERT INTO boot_versions (stage_name, version) VALUES (?, ?)
                    ON CONFLICT(stage_name) DO UPDATE SET version = excluded.version
                    WHERE excluded.version >= boot_versions.version
                    """,
                    (stage.name, stage.version),
                )
        return BootDecision("VERIFIED", True, "APPLICATION", ("Simulation boot chain verified",))
