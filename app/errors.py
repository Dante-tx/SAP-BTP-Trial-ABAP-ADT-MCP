class SapMcpError(Exception):
    """Base application error exposed as a controlled MCP failure."""


class ConfigError(SapMcpError):
    """Configuration is invalid or incomplete."""


class AuthorizationError(SapMcpError):
    """Caller is not authorized for the requested operation."""


class ValidationError(SapMcpError):
    """Request failed local validation before reaching SAP."""


class SapBackendError(SapMcpError):
    """SAP backend returned an error."""

