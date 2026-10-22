from dataclasses import dataclass

from optimus_swarm.envelope_verifier import verify_envelope
from optimus_swarm.replay_guard import ReplayGuard
from optimus_swarm.signed_envelope import SignedEnvelope


@dataclass(frozen=True)
class IngressDecision:
    accepted: bool
    reason_codes: tuple[str, ...]
    evidence_class: str | None
    physical_execution_authorized: bool = False


def receive_envelope(
    envelope: SignedEnvelope,
    *,
    trusted_keys: dict[str, dict],
    replay_guard: ReplayGuard,
    now_ms: int,
) -> IngressDecision:
    verification = verify_envelope(envelope, trusted_keys=trusted_keys, now_ms=now_ms)

    if not verification.accepted:
        return IngressDecision(
            accepted=False,
            reason_codes=verification.reason_codes,
            evidence_class=None,
        )

    reserved, reason = replay_guard.reserve(
        source_id=envelope.source_id,
        key_id=envelope.key_id,
        message_id=envelope.message_id,
        sequence_number=envelope.sequence_number,
    )

    if not reserved:
        return IngressDecision(
            accepted=False,
            reason_codes=(reason,),
            evidence_class=None,
        )

    return IngressDecision(
        accepted=True,
        reason_codes=("SIGNATURE_AND_REPLAY_CHECKS_PASSED",),
        evidence_class=envelope.evidence_class,
        physical_execution_authorized=False,
    )
