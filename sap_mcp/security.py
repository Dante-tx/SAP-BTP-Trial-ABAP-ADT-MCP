from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sap_mcp.config import AppConfig
from sap_mcp.errors import AuthorizationError


@dataclass(frozen=True)
class UserContext:
    subject: str
    roles: tuple[str, ...] = ()


SYSTEM_USER = UserContext(subject="mcp-http-client", roles=("abap.read", "abap.write"))


def token_values(config: AppConfig) -> set[str]:
    return {token.get_secret_value() for token in config.server.auth_tokens if token.get_secret_value()}


def check_tool_whitelist(tool_name: str, allowed_tools: set[str]) -> None:
    """Check if a tool is allowed by the configured whitelist.
    
    Args:
        tool_name: The name of the tool to check.
        allowed_tools: Set of allowed tool names. If "*" is present, all tools are allowed.
    
    Raises:
        AuthorizationError: If the tool is not in the whitelist.
    """
    if "*" in allowed_tools:
        return
    if tool_name in allowed_tools:
        return
    raise AuthorizationError(
        f"Tool '{tool_name}' is not in the allowed tools whitelist. "
        f"Configure 'server.allowed_tools' in sap-mcp.yaml to grant access."
    )


def authorize_tool(user: UserContext, tool_name: str, write: bool = False) -> None:
    if write and "abap.write" not in user.roles:
        raise AuthorizationError(f"User {user.subject} is not allowed to execute write tools")


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_tokens: Iterable[str]):
        super().__init__(app)
        self.allowed_tokens = set(allowed_tokens)

    async def dispatch(self, request: Request, call_next) -> Response:
        public_paths = {"/healthz", "/adt/redirect", "/logon/success"}
        if request.url.path in public_paths or not self.allowed_tokens:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or token not in self.allowed_tokens:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        request.state.user = UserContext(subject="bearer-token", roles=("abap.read", "abap.write"))
        return await call_next(request)
