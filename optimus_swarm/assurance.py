from dataclasses import dataclass
from typing import Mapping

REQUIRED_EVIDENCE = frozenset(
    {
        "threat_model_reviewed",
        "secure_boot_verified",
        "hardware_key_storage_verified",
        "signed_policy_verification_tested",
        "audit_tamper_tests_passed",
        "rollback_detection_tested",
        "network_loss_fail_closed_tested",
        "human_reset_authorization_tested",
        "independent_safety_controller_verified",
        "physical_emergency_stop_independently_tested",
        "independent_assessor_report",
    }
)


@dataclass(frozen=True)
class AssuranceReport:
    status: str
    passed_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    failed_evidence: tuple[str, ...]
    certification_granted: bool
    note: str


def assess_readiness(evidence: Mapping[str, bool]) -> AssuranceReport:
    """
    Evidence checklist only. This function cannot certify a robot,
    validate evidence authenticity, or establish regulatory compliance.
    """
    passed = tuple(
        sorted(key for key in REQUIRED_EVIDENCE if evidence.get(key) is True)
    )
    failed = tuple(
        sorted(
            key
            for key in REQUIRED_EVIDENCE
            if key in evidence and evidence[key] is False
        )
    )
    missing = tuple(sorted(key for key in REQUIRED_EVIDENCE if key not in evidence))

    if failed:
        status = "BLOCKED"
    elif missing:
        status = "INCOMPLETE"
    else:
        status = "READY_FOR_INDEPENDENT_REVIEW"

    return AssuranceReport(
        status=status,
        passed_evidence=passed,
        missing_evidence=missing,
        failed_evidence=failed,
        certification_granted=False,
        note=(
            "Readiness screening only. Evidence authenticity and technical "
            "claims require independent verification. No certification granted."
        ),
    )
