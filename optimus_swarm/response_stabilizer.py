from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from threading import RLock

from optimus_swarm.adaptive_response import AdaptiveDecision, ResponseGrade


class GradeRank(IntEnum):
    MONITOR = 0
    CAUTION = 1
    HUMAN_REVIEW = 2
    CRITICAL = 3


_RANK_TO_GRADE = {
    GradeRank.MONITOR: ResponseGrade.G0_MONITOR,
    GradeRank.CAUTION: ResponseGrade.G1_CAUTION,
    GradeRank.HUMAN_REVIEW: ResponseGrade.G2_HUMAN_REVIEW,
    GradeRank.CRITICAL: ResponseGrade.G3_CRITICAL_INHIBIT,
}


@dataclass(frozen=True)
class StabilizedDecision:
    response_grade: ResponseGrade
    reasons: tuple[str, ...]
    lower_risk_samples: int
    critical_latched: bool
    physical_execution_permitted: bool = False


class ResponseStabilizer:
    """
    In-process response hysteresis.

    This is not the authoritative safety latch. A persistent, authenticated
    OMEGA-GUARD service must own critical inhibit and human-authorized reset.
    """

    def __init__(self, *, downgrade_samples: int = 3):
        if isinstance(downgrade_samples, bool) or not isinstance(downgrade_samples, int) or downgrade_samples < 1:
            raise ValueError("downgrade_samples must be a positive integer")
        self._downgrade_samples = downgrade_samples
        self._current = GradeRank.MONITOR
        self._lower_count = 0
        self._critical_latched = False
        self._lock = RLock()

    @staticmethod
    def _rank(decision: AdaptiveDecision) -> GradeRank | None:
        mapping = {
            ResponseGrade.G0_MONITOR: GradeRank.MONITOR,
            ResponseGrade.G1_CAUTION: GradeRank.CAUTION,
            ResponseGrade.G2_HUMAN_REVIEW: GradeRank.HUMAN_REVIEW,
            ResponseGrade.G3_CRITICAL_INHIBIT: GradeRank.CRITICAL,
        }
        return mapping.get(decision.response_grade)

    def update(self, decision: AdaptiveDecision) -> StabilizedDecision:
        with self._lock:
            grade = decision.response_grade
            reasons = list(decision.reasons)
            if not decision.accepted or grade == ResponseGrade.G4_DATA_INVALID:
                self._lower_count = 0
                return StabilizedDecision(
                    response_grade=ResponseGrade.G4_DATA_INVALID,
                    reasons=tuple(reasons + ["FAIL_CLOSED_INVALID_DECISION"]),
                    lower_risk_samples=0,
                    critical_latched=self._critical_latched,
                )

            incoming = self._rank(decision)
            if incoming is None:
                self._lower_count = 0
                return StabilizedDecision(
                    response_grade=ResponseGrade.G4_DATA_INVALID,
                    reasons=tuple(reasons + ["UNKNOWN_RESPONSE_GRADE"]),
                    lower_risk_samples=0,
                    critical_latched=self._critical_latched,
                )

            if incoming == GradeRank.CRITICAL:
                self._critical_latched = True
                self._current = GradeRank.CRITICAL
                self._lower_count = 0
                return StabilizedDecision(
                    response_grade=ResponseGrade.G3_CRITICAL_INHIBIT,
                    reasons=tuple(reasons + ["CRITICAL_LATCHED"]),
                    lower_risk_samples=0,
                    critical_latched=True,
                )

            if self._critical_latched:
                return StabilizedDecision(
                    response_grade=ResponseGrade.G3_CRITICAL_INHIBIT,
                    reasons=tuple(reasons + ["HUMAN_AUTHORITY_RESET_REQUIRED"]),
                    lower_risk_samples=0,
                    critical_latched=True,
                )

            if incoming >= self._current:
                self._current = incoming
                self._lower_count = 0
            else:
                self._lower_count += 1
                if self._lower_count >= self._downgrade_samples:
                    self._current = incoming
                    self._lower_count = 0
                else:
                    reasons.append("DOWNGRADE_HELD_BY_HYSTERESIS")

            return StabilizedDecision(
                response_grade=_RANK_TO_GRADE[self._current],
                reasons=tuple(reasons),
                lower_risk_samples=self._lower_count,
                critical_latched=self._critical_latched,
            )
