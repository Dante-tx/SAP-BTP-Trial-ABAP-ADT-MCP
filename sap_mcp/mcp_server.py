from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from sap_mcp.config import AppConfig, get_config
from sap_mcp.security import SYSTEM_USER
from sap_mcp.services.abap_dev_gateway import AbapDevGateway
from sap_mcp.tools.official import register_official_tools


def create_mcp(config: AppConfig | None = None, *, stateless_http: bool = True) -> FastMCP:
    config = config or get_config()
    abap_gateway = AbapDevGateway(config.abap_dev)
    mcp = FastMCP(config.server.name, stateless_http=stateless_http, json_response=True)

    @mcp.tool()
    async def abap_adt_login() -> dict[str, Any]:
        """Reuse a valid local SSO session or open the ABAP ADT SSO login URL."""
        return await abap_gateway.login(SYSTEM_USER)

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

    register_official_tools(mcp, abap_gateway)

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
    async def abap_read_source(
        object_type: str | None = None,
        name: str | None = None,
        scope: str = "main",
        include_type: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        """Read ABAP source through ADT, including CLAS/INTF main, include, or composite views."""
        return await abap_gateway.read_source(SYSTEM_USER, object_type, name, scope, include_type, uri)

    @mcp.tool()
    async def abap_get_object_metadata(
        object_type: str | None = None,
        name: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        """Read ABAP object metadata through ADT and summarize links and source parts."""
        return await abap_gateway.get_object_metadata(SYSTEM_USER, object_type, name, uri)

    @mcp.tool()
    async def abap_create_object(
        object_type: str,
        name: str,
        package: str,
        description: str,
        reason: str,
        source: str | None = None,
        service_binding_version: str | None = None,
    ) -> dict[str, Any]:
        """Create an ABAP class or interface through ADT."""
        return await abap_gateway.create_object(
            SYSTEM_USER,
            object_type,
            name,
            package,
            description,
            reason,
            source,
            service_binding_version,
        )

    @mcp.tool()
    async def abap_update_source(
        source: str,
        etag: str,
        reason: str,
        object_type: str | None = None,
        name: str | None = None,
        include_type: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        """Update an ABAP source target through ADT using the matching uri/object ETag."""
        return await abap_gateway.update_source(SYSTEM_USER, object_type, name, source, etag, reason, include_type, uri)

    @mcp.tool()
    async def abap_activate_object(object_type: str, name: str, reason: str) -> dict[str, Any]:
        """Activate an ABAP class or interface through ADT."""
        return await abap_gateway.activate_object(SYSTEM_USER, object_type, name, reason)

    @mcp.tool()
    async def abap_activate_objects(objects: list[dict[str, str]], reason: str) -> dict[str, Any]:
        """Activate multiple ABAP repository objects through ADT."""
        return await abap_gateway.activate_objects(SYSTEM_USER, objects, reason)

    @mcp.tool()
    async def abap_delete_object(object_type: str, name: str, reason: str) -> dict[str, Any]:
        """Delete an ABAP repository object through ADT."""
        return await abap_gateway.delete_object(SYSTEM_USER, object_type, name, reason)

    @mcp.tool()
    async def abap_publish_service_binding(
        name: str, reason: str, odata_version: str | None = None
    ) -> dict[str, Any]:
        """Publish an OData V2 or V4 ABAP service binding through ADT."""
        return await abap_gateway.publish_service_binding(SYSTEM_USER, name, reason, odata_version)

    @mcp.tool()
    async def abap_run_unit_tests(
        objects: list[dict[str, str]] | None = None,
        packages: list[str] | None = None,
        include_subpackages: bool = True,
        title: str = "MCP ABAP Unit Run",
        wait_seconds: int = 0,
    ) -> dict[str, Any]:
        """Start an ABAP Unit run for ADT object sets and optionally wait for JUnit results."""
        return await abap_gateway.run_unit_tests(SYSTEM_USER, objects, packages, include_subpackages, title, wait_seconds)

    @mcp.tool()
    async def abap_get_unit_test_run(run_uri: str) -> dict[str, Any]:
        """Read the status of a previously started ABAP Unit run."""
        return await abap_gateway.get_unit_test_run(SYSTEM_USER, run_uri)

    @mcp.tool()
    async def abap_get_unit_test_result(result_uri: str) -> dict[str, Any]:
        """Read and summarize ABAP Unit JUnit XML results."""
        return await abap_gateway.get_unit_test_result(SYSTEM_USER, result_uri)

    @mcp.tool()
    async def abap_run_atc_checks(
        objects: list[dict[str, str]] | None = None,
        packages: list[str] | None = None,
        include_subpackages: bool = False,
        check_variant: str | None = None,
        configuration: str | None = None,
        wait_seconds: int = 0,
    ) -> dict[str, Any]:
        """Start an ATC check run for ADT object sets and optionally wait for checkstyle results."""
        return await abap_gateway.run_atc_checks(
            SYSTEM_USER, objects, packages, include_subpackages, check_variant, configuration, wait_seconds
        )

    @mcp.tool()
    async def abap_get_atc_run(run_uri: str) -> dict[str, Any]:
        """Read the status of a previously started ATC run."""
        return await abap_gateway.get_atc_run(SYSTEM_USER, run_uri)

    @mcp.tool()
    async def abap_get_atc_result(result_uri: str) -> dict[str, Any]:
        """Read and summarize ATC checkstyle XML results."""
        return await abap_gateway.get_atc_result(SYSTEM_USER, result_uri)

    return mcp
