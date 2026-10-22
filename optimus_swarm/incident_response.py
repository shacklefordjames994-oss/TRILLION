from dataclasses import dataclass
from enum import IntEnum
from threading import RLock
from typing import Callable
import hashlib
import json
import time


class Severity(IntEnum):
    INFO = 1
    WARNING = 2
    HIGH = 3
    CRITICAL = 4


CRITICAL_CODES = frozenset(
    {
        "SIGNATURE_INVALID",
        "POLICY_ROLLBACK_REJECTED",
        "AUDIT_INTEGRITY_FAILURE",
        "UNAUTHORIZED_POLICY_CHANGE",
        "SAFETY_STATE_UNAVAILABLE",
        "UNAPPROVED_PHYSICAL_COMMAND",
        "TRUSTED_STATE_REPLAY",
    }
)


@dataclass(frozen=True)
class Incident:
    incident_id: str
    timestamp_ns: int
    robot_id: str
    code: str
    severity: Severity
    description: str
    evidence_digest: str
    policy_revision: int
    status: str


@dataclass(frozen=True)
class IncidentResult:
    accepted: bool
    incident_id: str
    status: str
    actions: tuple[str, ...]


class IncidentResponseEngine:
    """
    In-process incident coordination for simulation and testing.

    Quarantine is a supplied callback. The callback must implement
    the actual storage policy for your shared-memory implementation.
    """

    def __init__(
        self,
        kill_switch,
        ledger,
        authorized_reviewers: set[str],
        quarantine_record: Callable[[str, str], bool],
        hardware=None,
    ):
        self._kill_switch = kill_switch
        self._ledger = ledger
        self._hardware = hardware
        self._reviewers = frozenset(
            x.strip() for x in authorized_reviewers if isinstance(x, str) and x.strip()
        )
        self._quarantine_record = quarantine_record
        self._lock = RLock()
        self._incidents: dict[str, Incident] = {}
        self._review_ids: set[str] = set()
        self._quarantined: set[str] = set()

        if not self._reviewers:
            raise ValueError("At least one authorized reviewer is required.")

    def _contain(self, robot_id: str, reason: str, actions: list) -> None:
        try:
            self._kill_switch.engage(robot_id, reason)
            actions.append("INHIBIT_REQUESTED")
        except Exception:
            actions.append("INHIBIT_REQUEST_FAILED")
        if self._hardware is not None:
            try:
                self._hardware.demand_stop(robot_id, reason)
                actions.append("HARDWARE_STOP_DEMANDED")
            except Exception:
                actions.append("HARDWARE_STOP_FAILED")

    @staticmethod
    def _digest_evidence(evidence: dict) -> str:
        # Digest only. Avoid storing raw sensitive payloads in the incident.
        encoded = json.dumps(
            evidence,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def report(
        self,
        robot_id: str,
        code: str,
        description: str,
        evidence: dict,
        policy_revision: int,
        memory_record_id: str | None = None,
    ) -> IncidentResult:
        if not isinstance(robot_id, str) or not robot_id.strip():
            robot_id = "UNKNOWN"
        if not isinstance(code, str) or not code.strip():
            code = "UNCLASSIFIED_FAILURE"
        if not isinstance(description, str) or not description.strip():
            description = "No description supplied."
        if not isinstance(policy_revision, int) or policy_revision < 0:
            policy_revision = 0

        # Severity is decided before evidence is touched.
        severity = (
            Severity.CRITICAL
            if code in CRITICAL_CODES
            else Severity.HIGH
            if code.startswith(("UNAPPROVED", "GUARD_"))
            else Severity.WARNING
        )

        incident_id = hashlib.sha256(
            f"{time.time_ns()}:{robot_id}:{code}".encode("utf-8")
        ).hexdigest()[:24]

        actions = []

        # Containment precedes evidence analysis, quarantine, and logging.
        if severity == Severity.CRITICAL:
            self._contain(robot_id, f"Incident {incident_id}: {code}", actions)

        if not isinstance(evidence, dict):
            evidence = {"evidence_format_error": True}

        try:
            evidence_digest = self._digest_evidence(evidence)
        except Exception:
            evidence_digest = "UNAVAILABLE"
            actions.append("EVIDENCE_DIGEST_FAILED")

        status = "OPEN"
        if memory_record_id:
            try:
                quarantined = self._quarantine_record(memory_record_id, incident_id)
                if quarantined:
                    self._quarantined.add(memory_record_id)
                    actions.append("MEMORY_QUARANTINED")
                else:
                    status = "QUARANTINE_FAILED"
                    actions.append("QUARANTINE_FAILED")
                    # A failed write must not leave the record usable.
                    self._quarantined.add(memory_record_id)
            except Exception:
                status = "QUARANTINE_FAILED"
                actions.append("QUARANTINE_FAILED")
                self._quarantined.add(memory_record_id)

        incident = Incident(
            incident_id=incident_id,
            timestamp_ns=time.time_ns(),
            robot_id=robot_id,
            code=code,
            severity=severity,
            description=description,
            evidence_digest=evidence_digest,
            policy_revision=policy_revision,
            status=status,
        )

        with self._lock:
            self._incidents[incident_id] = incident

        try:
            self._ledger.append(
                actor_id=robot_id,
                event_type=f"INCIDENT_{severity.name}",
                reason=(
                    f"id={incident_id}; code={code}; "
                    f"evidence_digest={incident.evidence_digest}"
                ),
            )
            if not self._ledger.verify():
                actions.append("LEDGER_VERIFICATION_FAILED")
                if severity != Severity.CRITICAL:
                    self._contain(robot_id, "Incident ledger integrity failure", actions)
        except Exception:
            actions.append("LEDGER_WRITE_FAILED")
            self._contain(robot_id, "Incident ledger unavailable", actions)

        return IncidentResult(
            accepted=True,
            incident_id=incident_id,
            status=status,
            actions=tuple(actions),
        )

    def is_quarantined(self, memory_record_id: str) -> bool:
        with self._lock:
            return memory_record_id in self._quarantined

    def get_incident(self, incident_id: str) -> Incident | None:
        with self._lock:
            return self._incidents.get(incident_id)

    def approve_review(
        self,
        incident_id: str,
        reviewer_id: str,
        review_id: str,
        disposition: str,
    ) -> bool:
        """
        Record a human review decision.

        This does not unquarantine a record, clear the kill switch,
        restart a task, or authorize physical execution.
        """
        if reviewer_id not in self._reviewers:
            raise PermissionError("Reviewer is not authorized.")
        if not review_id or not disposition:
            raise ValueError("Review ID and disposition are required.")

        with self._lock:
            if incident_id not in self._incidents:
                raise KeyError("Unknown incident.")
            if review_id in self._review_ids:
                raise ValueError("Review ID has already been used.")
            self._review_ids.add(review_id)

        self._ledger.append(
            actor_id=reviewer_id,
            event_type="INCIDENT_HUMAN_REVIEW",
            reason=(
                f"incident={incident_id}; review_id={review_id}; "
                f"disposition={disposition}"
            ),
        )
        return True
