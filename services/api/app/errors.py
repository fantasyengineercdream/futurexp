class DomainInvariantError(RuntimeError):
    """Raised when an internal runtime invariant is violated."""


class RuntimeExecutionError(RuntimeError):
    """Raised after a session has been explicitly marked failed."""


class SessionNotFound(LookupError):
    """Raised when a requested session does not exist."""


class OcImportNotFound(LookupError):
    """Raised when an OC import draft does not exist."""


class RegisteredOcNotFound(LookupError):
    """Raised when a confirmed OC does not exist."""
