from dataclasses import dataclass

from optimus_swarm.physical_inhibit import PhysicalExecutionInhibit


class HardwareStopRequired(PermissionError):
    """Raised when software or a robot tries to restore the safety chain."""


@dataclass(frozen=True)
class ChainStatus:
    estop_loop_closed: bool
    watchdog_closed: bool
    guard_closed: bool
    feedback_agrees: bool
    fault_latched: bool
    motion_power: bool
    actuator_output_enabled: bool
    reason: str


def _unavailable() -> ChainStatus:
    return ChainStatus(
        False,
        False,
        False,
        False,
        True,
        False,
        False,
        "SAFETY_CHAIN_UNAVAILABLE",
    )


class HardwareSafetyChain:
    """
    Series-wired safety-chain model.

    Any identified actor may open the chain. Only an allowlisted operator
    may release the E-stop or reset it, and only after the watchdog, guard,
    and contactor feedback agree. This process never enables an actuator
    output. It is not a safety-rated relay, contactor, or emergency stop.
    """

    SAFETY_PLC = "safety-plc"

    def __init__(self, reset_operators: set[str], watchdog_ms: int = 250):
        operators = frozenset(
            actor.strip()
            for actor in reset_operators
            if isinstance(actor, str) and actor.strip()
        )
        if not operators:
            raise ValueError("At least one hardware reset operator is required.")
        if isinstance(watchdog_ms, bool) or not isinstance(watchdog_ms, int) or watchdog_ms <= 0:
            raise ValueError("Watchdog interval must be a positive integer.")

        self._operators = operators
        self._watchdog_ms = watchdog_ms
        self._estop_pressed = True
        self._reset_closed = False
        self._guard_closed = True
        self._last_pulse_ms: int | None = None
        self._feedback_energized = False
        self._fault = False
        self._fault_reason = ""
        self._used_channels: set[str] = set()

    def evaluate(self, now_ms: int) -> ChainStatus:
        try:
            return self._evaluate(now_ms)
        except Exception:
            return _unavailable()

    def demand_stop(self, actor_id: str, reason: str) -> ChainStatus:
        """Open the E-stop loop. No privilege is granted by opening it."""
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise ValueError("actor_id is required.")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason is required.")
        self._estop_pressed = True
        self._reset_closed = False
        return self.evaluate(self._last_pulse_ms if self._last_pulse_ms is not None else 0)

    def release_estop(self, actor_id: str) -> ChainStatus:
        """Model a physical button release. This does not restore power."""
        if actor_id not in self._operators:
            raise HardwareStopRequired("Only a hardware operator can release the E-stop.")
        self._estop_pressed = False
        return self.evaluate(self._last_pulse_ms if self._last_pulse_ms is not None else 0)

    def pulse(self, source: str, now_ms: int) -> bool:
        """Only the safety-PLC source refreshes the watchdog."""
        if source != self.SAFETY_PLC:
            return False
        if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms < 0:
            return False
        self._last_pulse_ms = now_ms
        return True

    def open_guard(self, reason: str) -> ChainStatus:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason is required.")
        self._guard_closed = False
        self._reset_closed = False
        return self.evaluate(self._last_pulse_ms if self._last_pulse_ms is not None else 0)

    def close_guard(self, actor_id: str) -> ChainStatus:
        if actor_id not in self._operators:
            raise HardwareStopRequired("A robot cannot close a guard.")
        self._guard_closed = True
        return self.evaluate(self._last_pulse_ms if self._last_pulse_ms is not None else 0)

    def report_feedback(self, energized: bool, now_ms: int) -> ChainStatus:
        """Contactor feedback is an input, not a command to energize."""
        self._feedback_energized = bool(energized)
        return self.evaluate(now_ms)

    def hardware_reset(
        self,
        actor_id: str,
        channel_id: str,
        reason: str,
        now_ms: int,
    ) -> ChainStatus:
        """Close the reset contact. Does not enable actuator output."""
        if actor_id not in self._operators:
            raise HardwareStopRequired("Hardware reset requires an authorized operator.")
        if not isinstance(channel_id, str) or not channel_id.strip():
            raise HardwareStopRequired("A hardware channel id is required.")
        if not isinstance(reason, str) or not reason.strip():
            raise HardwareStopRequired("A hardware reset reason is required.")
        if self._estop_pressed:
            raise HardwareStopRequired("E-stop is still pressed.")
        if not self._guard_closed:
            raise HardwareStopRequired("Guard is open.")
        if not self._watchdog_ok(now_ms):
            raise HardwareStopRequired("Watchdog is open.")
        if self._feedback_energized:
            raise HardwareStopRequired("Contactor feedback is still energized.")

        channel = channel_id.strip()
        if channel in self._used_channels:
            raise HardwareStopRequired("Hardware channel id has already been used.")
        self._used_channels.add(channel)
        self._fault = False
        self._fault_reason = ""
        self._reset_closed = True
        return self.evaluate(now_ms)

    def actuator_command(self, command: str) -> tuple[bool, str]:
        allowed, _code = PhysicalExecutionInhibit().authorize(command)
        if allowed:
            return False, "PHYSICAL_EXECUTION_INHIBITED"
        return False, "NO_SAFETY_RATED_OUTPUT"

    def _watchdog_ok(self, now_ms: int) -> bool:
        if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms < 0:
            return False
        if self._last_pulse_ms is None or now_ms < self._last_pulse_ms:
            return False
        return (now_ms - self._last_pulse_ms) <= self._watchdog_ms

    def _demand(self, now_ms: int) -> bool:
        return (
            not self._estop_pressed
            and self._reset_closed
            and self._watchdog_ok(now_ms)
            and self._guard_closed
            and not self._fault
        )

    def _evaluate(self, now_ms: int) -> ChainStatus:
        if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms < 0:
            return _unavailable()

        demanded = self._demand(now_ms)
        if self._feedback_energized and not demanded:
            self._fault = True
            self._reset_closed = False
            self._fault_reason = "FEEDBACK_DISAGREES"
            demanded = False

        watchdog_closed = self._watchdog_ok(now_ms)
        agrees = self._feedback_energized == demanded and not self._fault
        motion = bool(demanded and self._feedback_energized and agrees)
        if self._fault:
            reason = self._fault_reason or "FAULT_LATCHED"
        elif self._estop_pressed:
            reason = "ESTOP_OPEN"
        elif not self._reset_closed:
            reason = "RESET_OPEN"
        elif not watchdog_closed:
            reason = "WATCHDOG_OPEN"
        elif not self._guard_closed:
            reason = "GUARD_OPEN"
        elif not self._feedback_energized:
            reason = "FEEDBACK_DEENERGIZED"
        elif motion:
            reason = "CHAIN_CLOSED_OUTPUT_STILL_DISABLED"
        else:
            reason = "CHAIN_OPEN"

        return ChainStatus(
            estop_loop_closed=not self._estop_pressed,
            watchdog_closed=watchdog_closed,
            guard_closed=self._guard_closed,
            feedback_agrees=agrees,
            fault_latched=self._fault,
            motion_power=motion,
            actuator_output_enabled=False,
            reason=reason,
        )
