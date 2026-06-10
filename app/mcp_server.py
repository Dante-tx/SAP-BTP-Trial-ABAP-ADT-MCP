from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.config import AppConfig, get_config
from app.security import SYSTEM_USER
from app.services.abap_dev_gateway import AbapDevGateway


def create_mcp(config: AppConfig | None = None) -> FastMCP:
    config = config or get_config()
    abap_gateway = AbapDevGateway(config.abap_dev)
    mcp = FastMCP(config.server.name, stateless_http=True, json_response=True)

    @mcp.tool()
    def abap_adt_login() -> dict[str, Any]:
        """Open the ABAP ADT SSO login URL in the local browser."""
        return abap_gateway.login(SYSTEM_USER)

    @mcp.tool()
    def abap_save_sso_session(cookies: dict[str, str], headers: dict[str, str] | None = None) -> dict[str, Any]:
        """Save browser SSO cookies for local ADT API calls."""
        return abap_gateway.save_session(SYSTEM_USER, cookies, headers)

    @mcp.tool()
    def abap_save_sso_cookie_header(cookie_header: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        """Save a raw browser Cookie header for local ADT API calls."""
        return abap_gateway.save_cookie_header(SYSTEM_USER, cookie_header, headers)

    @mcp.tool()
    async def abap_adt_connect() -> dict[str, Any]:
        """Validate that the saved SSO session can access ABAP ADT discovery."""
        return await abap_gateway.connect(SYSTEM_USER)

    @mcp.tool()
    async def abap_search_objects(
        query: str,
        max_results: int = 20,
        object_type: str | None = None,
        package: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search ABAP repository objects through ADT."""
        return await abap_gateway.search_objects(SYSTEM_USER, query, max_results, object_type, package)

    @mcp.tool()
    async def abap_read_source(object_type: str, name: str) -> dict[str, Any]:
        """Read ABAP class or interface source through ADT."""
        return await abap_gateway.read_source(SYSTEM_USER, object_type, name)

    @mcp.tool()
    async def abap_create_object(
        object_type: str,
        name: str,
        package: str,
        description: str,
        reason: str,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Create an ABAP class or interface through ADT."""
        return await abap_gateway.create_object(SYSTEM_USER, object_type, name, package, description, reason, source)

    @mcp.tool()
    async def abap_update_source(
        object_type: str,
        name: str,
        source: str,
        etag: str,
        reason: str,
    ) -> dict[str, Any]:
        """Update ABAP class or interface source through ADT using an ETag."""
        return await abap_gateway.update_source(SYSTEM_USER, object_type, name, source, etag, reason)

    @mcp.tool()
    async def abap_activate_object(object_type: str, name: str, reason: str) -> dict[str, Any]:
        """Activate an ABAP class or interface through ADT."""
        return await abap_gateway.activate_object(SYSTEM_USER, object_type, name, reason)

    @mcp.tool()
    async def abap_delete_object(object_type: str, name: str, reason: str) -> dict[str, Any]:
        """Delete an ABAP repository object through ADT."""
        return await abap_gateway.delete_object(SYSTEM_USER, object_type, name, reason)

    @mcp.tool()
    async def abap_publish_service_binding(name: str, reason: str) -> dict[str, Any]:
        """Publish an OData V4 ABAP service binding through ADT."""
        return await abap_gateway.publish_service_binding(SYSTEM_USER, name, reason)

    return mcp
