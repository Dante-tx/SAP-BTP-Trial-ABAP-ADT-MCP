from __future__ import annotations

from typing import Any


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

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {"error": str(self), "details": self.details}
