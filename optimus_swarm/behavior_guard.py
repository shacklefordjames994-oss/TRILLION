from dataclasses import dataclass
from typing import FrozenSet


@dataclass(frozen=True)
class BehaviorDecision:
    allowed: bool
    code: str
    action: str
    reason: str
    requires_human_review: bool


class BehaviorGuard:
    """
    Policy enforcement for a simulation-only robot command interface.
    This is not a certified safety controller.
    """

    def __init__(
        self,
        approved_simulation_actions: FrozenSet[str],
        ledger,
        kill_switch,
    ):
        self._approved = frozenset(approved_simulation_actions)
        self._ledger = ledger
        self._kill_switch = kill_switch

    def evaluate(self, robot_id: str, action: str, context: dict):
        def deny(code: str, reason: str):
            try:
                self._ledger.append(
                    actor_id=robot_id or "UNKNOWN",
                    event_type=code,
                    reason=f"action={action!r}; {reason}",
                )
            except Exception:
                # An audit failure must never turn a denial into approval.
                pass

            return BehaviorDecision(False, code, str(action), reason, True)

        try:
            if not isinstance(robot_id, str) or not robot_id.strip():
                return deny("INVALID_ACTOR", "Robot identity is missing.")

            if not isinstance(action, str) or not action.strip():
                return deny("INVALID_ACTION", "Action is missing.")

            if not isinstance(context, dict):
                return deny("INVALID_CONTEXT", "Context must be a dictionary.")

            if not self._ledger.verify():
                return deny("AUDIT_INTEGRITY_FAILURE", "Ledger verification failed.")

            state = self._kill_switch.state
            if state.latched:
                return deny("KILL_SWITCH_LATCHED", "System is inhibited.")

            if context.get("mode") != "SIMULATION":
                return deny("MODE_NOT_ALLOWED", "Only simulation mode is allowed.")

            if action not in self._approved:
                return deny("UNAPPROVED_BEHAVIOR", "Action is not on the allowlist.")

            if context.get("policy_verified") is not True:
                return deny("POLICY_UNVERIFIED", "Policy verification is missing.")

            if context.get("physical_actuation_requested") is True:
                return deny(
                    "PHYSICAL_EXECUTION_DISABLED",
                    "Physical actuation is prohibited by this prototype.",
                )

            self._ledger.append(
                actor_id=robot_id,
                event_type="SIMULATION_ACTION_APPROVED",
                reason=f"action={action}",
            )

            return BehaviorDecision(
                True,
                "SIMULATION_ACTION_APPROVED",
                action,
                "Approved for simulation only.",
                False,
            )

        except Exception:
            # Unknown errors fail closed.
            return BehaviorDecision(
                False,
                "GUARD_FAILURE",
                str(action),
                "Guard encountered an error; action rejected.",
                True,
            )
