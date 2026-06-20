from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from sap_mcp.config import AppConfig, get_config
from sap_mcp.connectors.core.registry import DEFAULT_MAX_RESULTS
from sap_mcp.errors import ValidationError
from sap_mcp.security import SYSTEM_USER
from sap_mcp.services.abap_dev_gateway import AbapDevGateway
from sap_mcp.tools.workflows import register_workflow_tools


def create_mcp(config: AppConfig | None = None, *, stateless_http: bool = True) -> FastMCP:
    config = config or get_config()
    allowed_tools = set(config.server.allowed_tools) if config.server.allowed_tools else {"*"}
    abap_gateway = AbapDevGateway(config.abap_dev, allowed_tools=allowed_tools)
    mcp = FastMCP(config.server.name, stateless_http=stateless_http, json_response=True)

    @mcp.tool()
    async def abap_adt_session(
        action: str = "login",
        cookies: dict[str, str] | None = None,
        cookie_header: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Manage ABAP ADT authentication. action: login, validate, save_cookies, save_cookie_header, or clear."""
        normalized = action.strip().lower()
        if normalized == "login":
            return await abap_gateway.login(SYSTEM_USER)
        if normalized in {"validate", "connect"}:
            return await abap_gateway.connect(SYSTEM_USER)
        if normalized == "save_cookies":
            if not cookies:
                raise ValidationError("cookies is required when action=save_cookies")
            return abap_gateway.save_session(SYSTEM_USER, cookies, headers)
        if normalized == "save_cookie_header":
            if not cookie_header:
                raise ValidationError("cookie_header is required when action=save_cookie_header")
            return abap_gateway.save_cookie_header(SYSTEM_USER, cookie_header, headers)
        if normalized == "clear":
            return abap_gateway.clear_session(SYSTEM_USER)
        raise ValidationError("action must be one of: login, validate, save_cookies, save_cookie_header, clear")

    register_workflow_tools(mcp, abap_gateway)

    @mcp.tool()
    async def abap_find_objects(
        query: str | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        object_type: str | None = None,
        package: str | None = None,
        exact_name: str | None = None,
        name: str | None = None,
        search_mode: str = "exact",
        sort_by: str | None = None,
    ) -> dict[str, Any]:
        """Find ABAP repository objects. Use name (or exact_name) for existence checks, package with no query to list a package, or query for search. search_mode can be exact, partial (wildcard), or description. sort_by can be name, type, or last_changed."""
        lookup_name = name or exact_name
        if lookup_name:
            if not object_type:
                raise ValidationError("object_type is required with name (or exact_name)")
            return await abap_gateway.object_exists(SYSTEM_USER, object_type, lookup_name)
        if package and not query:
            return {
                "package": package.upper(),
                "object_type": object_type,
                "results": await abap_gateway.list_package_objects(SYSTEM_USER, package, max_results, object_type),
            }
        search_query = query or "*"
        return {
            "query": search_query,
            "object_type": object_type,
            "package": package,
            "search_mode": search_mode,
            "sort_by": sort_by,
            "results": await abap_gateway.search_objects(SYSTEM_USER, search_query, max_results, object_type, package, search_mode, sort_by),
        }

    @mcp.tool()
    async def abap_read_source(
        object_type: str | None = None,
        name: str | None = None,
        scope: str = "main",
        include_type: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        """Read ABAP source through ADT. Use scope=include with include_type for CLAS/INTF includes; use scope=active/inactive for version-specific reads; use scope=both to compare active and inactive versions; use uri for an exact ADT source URI. For FUGR/FF (function module), you may pass just the function module name; the function group will be resolved automatically."""
        return await abap_gateway.read_source(SYSTEM_USER, object_type, name, scope, include_type, uri)

    @mcp.tool()
    async def abap_describe_signature(
        object_type: str,
        name: str,
        method_name: str | None = None,
    ) -> dict[str, Any]:
        """Describe the parameter signature of an ABAP callable object. Supports FUGR/FF (function module), CLAS/CI (class method), and INTF/IF (interface method). For FUGR/FF, method_name is ignored; for CLAS/CI and INTF/IF, method_name is required. Returns structured importing/exporting/changing/returning parameters with name, type, optional flag, default value, and pass-by mode."""
        return await abap_gateway.describe_signature(SYSTEM_USER, object_type, name, method_name)

    @mcp.tool()
    async def abap_get_object_metadata(
        object_type: str | None = None,
        name: str | None = None,
        uri: str | None = None,
        destination: str | None = None,
    ) -> dict[str, Any]:
        """Read ABAP object metadata, package, links, and source part descriptors. destination is accepted for signature consistency; the configured ADT system is used. For FUGR/FF (function module), you may pass just the function module name; the function group will be resolved automatically."""
        return await abap_gateway.get_object_metadata(SYSTEM_USER, object_type, name, uri, destination)

    @mcp.tool()
    async def abap_create_object(
        object_type: str,
        name: str | None = None,
        package: str | None = None,
        description: str | None = None,
        reason: str = "Create ABAP repository object",
        source: str | None = None,
        service_binding_version: str | None = None,
        destination: str | None = None,
        object_content: str | dict[str, Any] | None = None,
        transport_request_number: str | None = None,
        implementation_type: str | None = None,
    ) -> dict[str, Any]:
        """Create one ABAP repository object. Simple mode: object_type/name/package/description/source. Schema mode: object_type/object_content/destination/transport_request_number. For BDEF: pass implementation_type (Managed/Unmanaged/Abstract/Projection) and optional transport_request_number. For SRVB: source is the service definition name, service_binding_version controls OData V2/V4."""
        return await abap_gateway.create_object(
            SYSTEM_USER,
            object_type,
            name,
            package,
            description,
            reason,
            source,
            service_binding_version,
            destination,
            object_content,
            transport_request_number,
            implementation_type,
        )

    @mcp.tool()
    async def abap_update_source(
        source: str,
        reason: str,
        etag: str | None = None,
        object_type: str | None = None,
        name: str | None = None,
        include_type: str | None = None,
        uri: str | None = None,
        transport_request_number: str | None = None,
    ) -> dict[str, Any]:
        """Update one exact ADT source target. Pass etag for strict concurrency checks, or omit it to auto-read the latest ADT etag before writing. For CLAS/INTF includes, pass include_type or uri. Pass transport_request_number for OP systems requiring corrNr."""
        return await abap_gateway.update_source(SYSTEM_USER, object_type, name, source, etag, reason, include_type, uri, transport_request_number)

    @mcp.tool()
    async def abap_activate(
        reason: str,
        object_type: str | None = None,
        name: str | None = None,
        objects: list[dict[str, str]] | None = None,
        cascade: bool = False,
    ) -> dict[str, Any]:
        """Activate one or more ABAP repository objects. Pass object_type/name for one object, or objects for batch activation. Set cascade=true for PROG to automatically include all INCLUDE dependencies."""
        if objects:
            return await abap_gateway.activate_objects(SYSTEM_USER, objects, reason)
        if not object_type or not name:
            raise ValidationError("Provide object_type and name, or objects")
        return await abap_gateway.activate_object(SYSTEM_USER, object_type, name, reason, cascade=cascade)

    @mcp.tool()
    async def abap_delete_object(
        object_type: str,
        name: str,
        reason: str,
        etag: str | None = None,
        transport_request_number: str | None = None,
    ) -> dict[str, Any]:
        """Delete an ABAP repository object through ADT. Pass transport_request_number to record deletion in an existing OP transport request; pass etag or omit it to let the tool read/retry ADT etags."""
        return await abap_gateway.delete_object(SYSTEM_USER, object_type, name, reason, etag, transport_request_number)

    @mcp.tool()
    async def abap_publish_service_binding(
        name: str, reason: str, odata_version: str | None = None
    ) -> dict[str, Any]:
        """Publish an OData V2 or V4 ABAP service binding through ADT."""
        return await abap_gateway.publish_service_binding(SYSTEM_USER, name, reason, odata_version)

    @mcp.tool()
    async def abap_unpublish_service_binding(
        name: str, reason: str, odata_version: str | None = None
    ) -> dict[str, Any]:
        """Unpublish an OData V2 or V4 ABAP service binding through ADT."""
        return await abap_gateway.unpublish_service_binding(SYSTEM_USER, name, reason, odata_version)

    @mcp.tool()
    async def abap_quality(
        kind: str,
        action: str = "start",
        objects: list[dict[str, str]] | None = None,
        packages: list[str] | None = None,
        include_subpackages: bool = True,
        title: str = "MCP ABAP Unit Run",
        wait_seconds: int = 0,
        run_uri: str | None = None,
        result_uri: str | None = None,
        check_variant: str | None = None,
        configuration: str | None = None,
    ) -> dict[str, Any]:
        """Run or inspect ABAP quality checks. kind: unit or atc. action: start, status, or result."""
        normalized_kind = kind.strip().lower()
        normalized_action = action.strip().lower()
        if normalized_kind not in {"unit", "atc"}:
            raise ValidationError("kind must be unit or atc")
        if normalized_action == "start":
            if normalized_kind == "unit":
                return await abap_gateway.run_unit_tests(SYSTEM_USER, objects, packages, include_subpackages, title, wait_seconds)
            return await abap_gateway.run_atc_checks(
                SYSTEM_USER, objects, packages, include_subpackages, check_variant, configuration, wait_seconds
            )
        if normalized_action == "status":
            if not run_uri:
                raise ValidationError("run_uri is required when action=status")
            if normalized_kind == "unit":
                return await abap_gateway.get_unit_test_run(SYSTEM_USER, run_uri)
            return await abap_gateway.get_atc_run(SYSTEM_USER, run_uri)
        if normalized_action == "result":
            if not result_uri:
                raise ValidationError("result_uri is required when action=result")
            if normalized_kind == "unit":
                return await abap_gateway.get_unit_test_result(SYSTEM_USER, result_uri)
            return await abap_gateway.get_atc_result(SYSTEM_USER, result_uri)
        raise ValidationError("action must be start, status, or result")

    @mcp.tool()
    async def abap_where_used(
        object_type: str,
        name: str,
        enable_all_types: bool = False,
    ) -> dict[str, Any]:
        """Find where an ABAP object is used (Where-Used list). Returns references with name, type, description. Set enable_all_types=true to search all reference types (like Eclipse 'Select All')."""
        return await abap_gateway.where_used(SYSTEM_USER, object_type, name, enable_all_types)

    @mcp.tool()
    async def abap_syntax_check(
        source: str,
        object_type: str,
        name: str,
    ) -> dict[str, Any]:
        """Run ABAP syntax check on source code without activating it. Returns errors, warnings, and info with line numbers and severity counts."""
        return await abap_gateway.syntax_check(SYSTEM_USER, source, object_type, name)

    @mcp.tool()
    async def abap_data_preview(
        action: str,
        object_name: str | None = None,
        top: int = 100,
        select_fields: str | None = None,
        filter: str | None = None,
        orderby: str | None = None,
    ) -> dict[str, Any]:
        """Preview data from CDS views, DDIC tables, or free-style SQL queries. action: cds, ddic, or freestyle. For freestyle, pass the complete SELECT statement in object_name; the tool sends it as text/plain request body."""
        return await abap_gateway.data_preview(SYSTEM_USER, action, object_name, top, select_fields, filter, orderby)

    @mcp.tool()
    async def abap_cds_analysis(
        action: str,
        object_type: str = "DDLS",
        object_name: str | None = None,
        relation_type: str = "network",
    ) -> dict[str, Any]:
        """Analyze CDS views. action: dependencies, related_objects, active_object, create_sql, or object_relations."""
        return await abap_gateway.cds_analysis(SYSTEM_USER, action, object_type, object_name, relation_type)

    @mcp.tool()
    async def abap_code_assist(
        action: str,
        object_type: str,
        object_name: str | None = None,
        source: str | None = None,
        position: str | None = None,
    ) -> dict[str, Any]:
        """Assist ABAP code editing. action: element_info or format."""
        return await abap_gateway.code_assist(SYSTEM_USER, action, object_type, object_name, source, position)

    @mcp.tool()
    async def abap_execute(
        action: str,
        object_name: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute ABAP programs or classes. action: program or class."""
        return await abap_gateway.execute(SYSTEM_USER, action, object_name, parameters)

    @mcp.tool()
    async def abap_call_function(
        function_name: str,
        confirmed: bool = False,
        importing: dict[str, Any] | None = None,
        changing: dict[str, Any] | None = None,
        tables: dict[str, list[dict[str, Any]]] | None = None,
        destination: str | None = None,
        commit: bool = False,
    ) -> dict[str, Any]:
        """[HIGH RISK — Requires explicit confirmation] Execute an ABAP function module by creating a temporary ZMCP_FM_* class in $TMP, activating, running, then deleting it. Set confirmed=true to proceed after reviewing the warning below."""
        if not confirmed:
            return {
                "warning": True,
                "message": (
                    f"⚠️ **高风险操作 — 需要您确认**\n\n"
                    f"调用函数模块 **{function_name}** 将通过以下方式在 ABAP 系统中执行：\n\n"
                    f"1. 在包 **$TMP** 中创建一个临时类（名称格式 `ZCL_FM_MCP_*`）\n"
                    f"2. 将函数调用代码注入该类并激活\n"
                    f"3. 执行该类（`if_oo_adt_classrun~main`）\n"
                    f"4. 执行完毕后自动删除该临时类\n\n"
                    f"**操作详情：**\n"
                    f"- 函数模块：{function_name}\n"
                    f"- 提交事务（commit）：{'是' if commit else '否'}\n"
                    f"- 远程目标（destination）：{destination or '无（本地调用）'}\n\n"
                    f"**风险说明：**\n"
                    f"- 该操作会在系统中短暂创建并激活一个临时类\n"
                    f"- 如果 `commit=true`，对数据库的修改将直接提交，无法回滚\n"
                    f"- 请仅在了解函数行为的情况下执行\n\n"
                    f"如果确认无误，请将参数 **`confirmed=True`** 再次发起调用。"
                ),
            }
        return await abap_gateway.call_function(
            SYSTEM_USER, function_name, importing, changing, tables, destination, commit
        )

    @mcp.tool()
    async def abap_system_info(
        action: str,
    ) -> dict[str, Any]:
        """Read ABAP system information. action: system, components, or users."""
        return await abap_gateway.system_info(SYSTEM_USER, action)

    return mcp
