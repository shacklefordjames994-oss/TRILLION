class PhysicalExecutionDenied(PermissionError):
    """Raised when code attempts to release the physical-execution inhibit."""


class PhysicalExecutionInhibit:
    """
    Hard deny for actuator output.

    This object has no enabled state. Clearing the simulation latch, resetting
    a hardware-chain model, or approving a simulation proposal does not release it.
    """

    CODE = "PHYSICAL_EXECUTION_INHIBITED"

    def engaged(self) -> bool:
        return True

    def permits(self) -> bool:
        return False

    def authorize(self, request: object = None) -> tuple[bool, str]:
        del request
        return False, self.CODE

    def release(self, actor_id: str = "", authorization_id: str = "") -> bool:
        del actor_id, authorization_id
        raise PhysicalExecutionDenied("Physical execution inhibit cannot be released by this service.")
