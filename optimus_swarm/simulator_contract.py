class IdempotentSimulator:
    """In-process simulator. command_id is the idempotency key. No hardware."""

    def __init__(self):
        self._effects: dict[str, str] = {}

    @property
    def effect_count(self) -> int:
        return len(self._effects)

    def dispatch(self, command_id: str, event_digest: str, *, inhibit_clear: bool) -> str:
        if not inhibit_clear:
            return "INHIBIT_LATCHED"
        prior = self._effects.get(command_id)
        if prior is None:
            self._effects[command_id] = event_digest
            return "SIMULATION_EXECUTED"
        if prior != event_digest:
            return "INDETERMINATE"
        return "SIMULATION_EXECUTED"
