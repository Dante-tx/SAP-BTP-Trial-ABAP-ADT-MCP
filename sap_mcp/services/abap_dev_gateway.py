from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sap_mcp.auth.browser_sso import BrowserSsoSessionManager
from sap_mcp.config import AbapDevConfig
from sap_mcp.connectors.adt import AdtConnector
from sap_mcp.connectors.core.registry import DEFAULT_MAX_RESULTS, DEFAULT_PACKAGE_LIST_LIMIT
from sap_mcp.errors import AuthorizationError, ConfigError, ValidationError
from sap_mcp.security import UserContext, authorize_tool, check_tool_whitelist


T = TypeVar("T")

class AbapDevGateway:
    def __init__(self, config: AbapDevConfig, *, allowed_tools: set[str] | None = None):
        self.config = config
        self.sessions = BrowserSsoSessionManager(config)
        self.allowed_tools = allowed_tools or {"*"}

    async def login(self, user: UserContext) -> dict[str, Any]:
        check_tool_whitelist("abap_adt_session", self.allowed_tools)
        authorize_tool(user, "abap_adt_session")
        return await self.sessions.login()

    def save_session(
        self, user: UserContext, cookies: dict[str, str], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        check_tool_whitelist("abap_adt_session", self.allowed_tools)
        authorize_tool(user, "abap_adt_session", write=True)
        return self.sessions.save_session(cookies, headers)

    def save_cookie_header(
        self, user: UserContext, cookie_header: str, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        check_tool_whitelist("abap_adt_session", self.allowed_tools)
        authorize_tool(user, "abap_adt_session", write=True)
        return self.sessions.save_cookie_header(cookie_header, headers)

    def clear_session(self, user: UserContext) -> dict[str, Any]:
        check_tool_whitelist("abap_adt_session", self.allowed_tools)
        authorize_tool(user, "abap_adt_session", write=True)
        return self.sessions.clear_session()

    async def _read_operation(
        self,
        user: UserContext,
        tool_name: str,
        operation: Callable[[AdtConnector], Awaitable[T]],
        action: str,
    ) -> T:
        return await self._run_with_connector(
            user,
            tool_name,
            operation,
            expired_message=self._expired_message(action),
        )

    async def _write_operation(
        self,
        user: UserContext,
        tool_name: str,
        operation: Callable[[AdtConnector], Awaitable[T]],
        action: str,
    ) -> T:
        return await self._run_with_connector(
            user,
            tool_name,
            operation,
            expired_message=self._expired_message(action),
            write=True,
        )

    async def _quality_operation(
        self,
        user: UserContext,
        operation: Callable[[AdtConnector], Awaitable[T]],
        action: str,
    ) -> T:
        return await self._run_with_connector(
            user,
            "abap_quality",
            operation,
            quality_action=action,
        )

    async def connect(self, user: UserContext) -> dict[str, Any]:
        check_tool_whitelist("abap_adt_session", self.allowed_tools)
        authorize_tool(user, "abap_adt_session")
        _connector, discovery = await self._authenticated_connector()
        return discovery

    async def search_objects(
        self,
        user: UserContext,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        object_type: str | None = None,
        package: str | None = None,
        search_mode: str = "exact",
        sort_by: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._read_operation(
            user,
            "abap_find_objects",
            lambda connector: connector.search_objects(query, max_results, object_type, package, search_mode, sort_by),
            "searching ABAP objects",
        )

    async def list_package_objects(
        self,
        user: UserContext,
        package: str,
        max_results: int = DEFAULT_PACKAGE_LIST_LIMIT,
        object_type: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._read_operation(
            user,
            "abap_find_objects",
            lambda connector: connector.list_package_objects(package, max_results, object_type),
            "listing ABAP package objects",
        )

    async def object_exists(self, user: UserContext, object_type: str, name: str) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_find_objects",
            lambda connector: connector.object_exists(object_type, name),
            "checking ABAP object existence",
        )

    async def read_source(
        self,
        user: UserContext,
        object_type: str | None = None,
        name: str | None = None,
        scope: str | None = None,
        include_type: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_read_source",
            lambda connector: connector.read_source(object_type, name, scope, include_type, uri),
            "reading ABAP source",
        )

    async def describe_signature(
        self,
        user: UserContext,
        object_type: str,
        name: str,
        method_name: str | None = None,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_describe_signature",
            lambda connector: connector.describe_signature(object_type, name, method_name),
            "describing ABAP signature",
        )

    async def get_object_metadata(
        self,
        user: UserContext,
        object_type: str | None = None,
        name: str | None = None,
        uri: str | None = None,
        destination: str | None = None,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_get_object_metadata",
            lambda connector: connector.get_object_metadata(object_type, name, uri),
            "reading ABAP object metadata",
        )

    async def create_object(
        self,
        user: UserContext,
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
        if object_content is not None:
            return await self._handle_object_content_create(
                user, object_type, reason, service_binding_version,
                destination, object_content, transport_request_number, implementation_type,
            )

        if not name or not package or not description:
            raise ValidationError(
                "abap_create_object requires name, package, and description for the simplified workflow; "
                "or pass object_content JSON for schema-driven creation."
            )
        return await self._handle_simple_create(
            user, object_type, name, package, description, reason,
            source, service_binding_version, transport_request_number, implementation_type,
        )

    async def _handle_object_content_create(
        self,
        user: UserContext,
        object_type: str,
        reason: str,
        service_binding_version: str | None,
        destination: str | None,
        object_content: str | dict[str, Any],
        transport_request_number: str | None,
        implementation_type: str | None,
    ) -> dict[str, Any]:
        """Handle creation from object_content JSON (schema-driven workflow)."""
        if isinstance(object_content, dict):
            content = object_content
            object_content_payload = json.dumps(object_content)
        else:
            object_content_payload = object_content
            try:
                content = json.loads(object_content)
            except json.JSONDecodeError as exc:
                raise ValidationError("object_content must be a JSON object string") from exc
        if not isinstance(content, dict):
            raise ValidationError("object_content must be a JSON object string")

        content_name = self._first_content_value(content, "name", "objectName")
        content_package = self._first_content_value(content, "packageName", "package", "developmentPackage")
        content_description = self._first_content_value(content, "description", "label")
        if content_name and content_package and content_description:
            return await self._write_operation(
                user, "abap_create_object",
                lambda connector: connector.create_object(
                    object_type,
                    content_name, content_package, content_description, reason,
                    self._extract_content_source(content, object_type),
                    service_binding_version or self._first_content_value(content, "serviceBindingVersion", "service_binding_version"),
                    transport_request_number=transport_request_number,
                    implementation_type=implementation_type or self._first_content_value(content, "implementationType", "implementation_type"),
                ),
                "creating the ABAP object",
            )
        return await self._write_operation(
            user, "abap_create_object",
            lambda connector: connector.creation_create_object(
                destination or "", object_type, object_content_payload, transport_request_number,
            ),
            "creating the ABAP object",
        )

    @staticmethod
    def _extract_content_source(content: dict[str, Any], object_type: str) -> str | None:
        """Extract source field from object_content, with type-specific overrides."""
        source = None
        normalized_type = object_type.split("/", 1)[0].upper()
        if normalized_type == "FUNC":
            source = AbapDevGateway._first_content_value(content, "parentName", "functionGroup", "function_group")
        if normalized_type == "SRVB":
            source = AbapDevGateway._first_content_value(content, "serviceDefinition", "service_definition")
        return source or AbapDevGateway._first_content_value(content, "source", "abapSource", "body")

    async def _handle_simple_create(
        self,
        user: UserContext,
        object_type: str,
        name: str,
        package: str,
        description: str,
        reason: str,
        source: str | None,
        service_binding_version: str | None,
        transport_request_number: str | None,
        implementation_type: str | None,
    ) -> dict[str, Any]:
        """Handle creation from explicit parameters (simplified workflow)."""
        return await self._write_operation(
            user, "abap_create_object",
            lambda connector: connector.create_object(
                object_type, name, package, description, reason, source,
                service_binding_version,
                transport_request_number=transport_request_number,
                implementation_type=implementation_type,
            ),
            "creating the ABAP object",
        )

    @staticmethod
    def _first_content_value(content: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = content.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    async def update_source(
        self,
        user: UserContext,
        object_type: str | None,
        name: str | None,
        source: str,
        etag: str | None,
        reason: str,
        include_type: str | None = None,
        uri: str | None = None,
        transport_request_number: str | None = None,
    ) -> dict[str, Any]:
        return await self._write_operation(
            user,
            "abap_update_source",
            lambda connector: connector.update_source(object_type, name, source, etag, reason, include_type, uri, transport_request_number),
            "updating ABAP source",
        )

    async def activate_object(
        self, user: UserContext, object_type: str, name: str, reason: str,
        cascade: bool = False,
    ) -> dict[str, Any]:
        return await self._write_operation(
            user,
            "abap_activate",
            lambda connector: connector.activate_object(object_type, name, reason, cascade=cascade),
            "activating the ABAP object",
        )

    async def activate_objects(self, user: UserContext, objects: list[dict[str, str]], reason: str) -> dict[str, Any]:
        return await self._write_operation(
            user,
            "abap_activate",
            lambda connector: connector.activate_objects(objects, reason),
            "activating ABAP objects",
        )

    async def delete_object(
        self,
        user: UserContext,
        object_type: str,
        name: str,
        reason: str,
        etag: str | None = None,
        transport_request_number: str | None = None,
    ) -> dict[str, Any]:
        return await self._write_operation(
            user,
            "abap_delete_object",
            lambda connector: connector.delete_object(object_type, name, reason, etag, transport_request_number),
            "deleting the ABAP object",
        )

    async def publish_service_binding(
        self, user: UserContext, name: str, reason: str, odata_version: str | None = None
    ) -> dict[str, Any]:
        return await self._write_operation(
            user,
            "abap_publish_service_binding",
            lambda connector: connector.publish_service_binding(name, reason, odata_version),
            "publishing the service binding",
        )

    async def unpublish_service_binding(
        self, user: UserContext, name: str, reason: str, odata_version: str | None = None
    ) -> dict[str, Any]:
        return await self._write_operation(
            user,
            "abap_unpublish_service_binding",
            lambda connector: connector.unpublish_service_binding(name, reason, odata_version),
            "unpublishing the service binding",
        )

    async def run_unit_tests(
        self,
        user: UserContext,
        objects: list[dict[str, str]] | None = None,
        packages: list[str] | None = None,
        include_subpackages: bool = True,
        title: str = "MCP ABAP Unit Run",
        wait_seconds: int = 0,
    ) -> dict[str, Any]:
        return await self._quality_operation(
            user,
            lambda connector: connector.run_unit_tests(objects, packages, include_subpackages, title, wait_seconds),
            "running ABAP Unit tests",
        )

    async def get_unit_test_run(self, user: UserContext, run_uri: str) -> dict[str, Any]:
        return await self._quality_operation(
            user,
            lambda connector: connector.get_unit_test_run(run_uri),
            "reading the ABAP Unit run",
        )

    async def get_unit_test_result(self, user: UserContext, result_uri: str) -> dict[str, Any]:
        return await self._quality_operation(
            user,
            lambda connector: connector.get_unit_test_result(result_uri),
            "reading the ABAP Unit result",
        )

    async def run_atc_checks(
        self,
        user: UserContext,
        objects: list[dict[str, str]] | None = None,
        packages: list[str] | None = None,
        include_subpackages: bool = True,
        check_variant: str | None = None,
        configuration: str | None = None,
        wait_seconds: int = 0,
    ) -> dict[str, Any]:
        return await self._quality_operation(
            user,
            lambda connector: connector.run_atc_checks(
                objects, packages, include_subpackages, check_variant, configuration, wait_seconds
            ),
            "running ATC checks",
        )

    async def get_atc_run(self, user: UserContext, run_uri: str) -> dict[str, Any]:
        return await self._quality_operation(
            user,
            lambda connector: connector.get_atc_run(run_uri),
            "reading the ATC run",
        )

    async def get_atc_result(self, user: UserContext, result_uri: str) -> dict[str, Any]:
        return await self._quality_operation(
            user,
            lambda connector: connector.get_atc_result(result_uri),
            "reading the ATC result",
        )

    # ── Workflow operations (merged from WorkflowGatewayMixin) ──────────────

    async def list_destinations(self, user: UserContext) -> list[str]:
        return await self._read_operation(
            user,
            "abap_list_destinations",
            lambda connector: connector.list_destinations(),
            "listing ABAP destinations",
        )

    async def activate_uris(self, user: UserContext, uris: list[str], reason: str) -> dict[str, Any]:
        return await self._write_operation(
            user,
            "abap_activate",
            lambda connector: connector.activate_objects(connector.uri_objects(uris), reason),
            "activating ABAP objects",
        )

    async def run_unit_tests_for_uris(
        self,
        user: UserContext,
        uris: list[str],
        include_subpackages: bool = True,
        title: str = "MCP ABAP Unit Run",
        wait_seconds: int = 0,
    ) -> dict[str, Any]:
        return await self._quality_operation(
            user,
            lambda connector: connector.run_unit_tests(
                connector.uri_objects(uris), None, include_subpackages, title, wait_seconds
            ),
            "running ABAP Unit tests",
        )

    async def creation_get_all_creatable_objects(self, user: UserContext, destination: str) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_creation_info",
            lambda connector: connector.creation_get_all_creatable_objects(destination),
            "listing creatable ABAP object types",
        )

    async def creation_get_object_type_details(
        self,
        user: UserContext,
        destination: str,
        object_type: str,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_creation_info",
            lambda connector: connector.creation_get_object_type_details(destination, object_type, name, description),
            "reading ABAP object creation details",
        )

    async def creation_run_validation(
        self, user: UserContext, destination: str, object_type: str, object_content: str
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_creation_info",
            lambda connector: connector.creation_run_validation(destination, object_type, object_content),
            "validating ABAP object creation",
        )

    async def generators_list_generators(self, user: UserContext, destination: str) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_generators",
            lambda connector: connector.generators_list_generators(destination),
            "listing RAP generators",
        )

    async def generators_get_schema(
        self,
        user: UserContext,
        destination: str,
        generator_id: str,
        package_name: str,
        referenced_object_type: str,
        referenced_object_name: str,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_generators",
            lambda connector: connector.generators_get_schema(
                destination, generator_id, package_name, referenced_object_type, referenced_object_name
            ),
            "reading the RAP generator schema",
        )

    async def generators_generate_objects(
        self,
        user: UserContext,
        destination: str,
        generator_id: str,
        content: str,
        package_name: str,
        transport_request_number: str,
        referenced_object_type: str,
        referenced_object_name: str,
    ) -> dict[str, Any]:
        return await self._write_operation(
            user,
            "abap_generators",
            lambda connector: connector.generators_generate_objects(
                destination,
                generator_id,
                content,
                package_name,
                transport_request_number,
                referenced_object_type,
                referenced_object_name,
            ),
            "generating RAP objects",
        )

    async def transport_get(
        self,
        user: UserContext,
        destination: str,
        object_name: str,
        object_type: str,
        development_package: str,
        is_creation: bool,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_transport",
            lambda connector: connector.transport_get(
                destination, development_package, object_name, object_type, is_creation
            ),
            "reading transport requests",
        )

    async def transport_create(
        self,
        user: UserContext,
        destination: str,
        development_package: str,
        transport_description: str,
        is_creation: bool,
        object_name: str | None = None,
        object_type: str | None = None,
    ) -> dict[str, Any]:
        return await self._write_operation(
            user,
            "abap_transport",
            lambda connector: connector.transport_create(
                destination, development_package, transport_description, is_creation, object_name, object_type
            ),
            "creating the transport request",
        )

    async def transport_list_tasks(
        self, user: UserContext, transport_request_number: str
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_transport",
            lambda connector: connector.transport_list_tasks(transport_request_number),
            "listing transport tasks",
        )

    async def transport_list_objects(
        self, user: UserContext, transport_request_number: str
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_transport",
            lambda connector: connector.transport_list_objects(transport_request_number),
            "listing transport objects",
        )

    async def transport_release(
        self, user: UserContext, transport_request_number: str
    ) -> dict[str, Any]:
        return await self._write_operation(
            user,
            "abap_transport",
            lambda connector: connector.transport_release(transport_request_number),
            "releasing the transport request",
        )

    async def lock_object(
        self,
        user: UserContext,
        object_url: str,
        is_creation: bool = False,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_transport",
            lambda connector: connector.lock_object(object_url, is_creation=is_creation),
            "locking the ABAP object",
        )

    async def unlock_object(
        self,
        user: UserContext,
        lock_handle: str,
        object_url: str,
    ) -> None:
        await self._read_operation(
            user,
            "abap_transport",
            lambda connector: connector.unlock_object(lock_handle, object_url),
            "unlocking the ABAP object",
        )

    async def where_used(
        self,
        user: UserContext,
        object_type: str,
        name: str,
        enable_all_types: bool = False,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_where_used",
            lambda connector: connector.where_used(object_type, name, enable_all_types),
            "finding where-used references",
        )

    async def syntax_check(
        self,
        user: UserContext,
        source: str,
        object_type: str,
        name: str,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_syntax_check",
            lambda connector: connector.syntax_check(source, object_type, name),
            "running syntax check",
        )

    async def business_services_fetch_services(
        self, user: UserContext, destination: str, service_binding_name: str
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_business_services",
            lambda connector: connector.business_services_fetch_services(destination, service_binding_name),
            "reading business services",
        )

    async def business_services_fetch_service_information(
        self,
        user: UserContext,
        destination: str,
        service_binding_name: str,
        service_name: str | None = None,
        service_definition: str | None = None,
        service_version: str | None = None,
        odata_info_uri: str | None = None,
        odata_version: str | None = None,
        is_published: bool | None = None,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_business_services",
            lambda connector: connector.business_services_fetch_service_information(
                destination,
                service_binding_name,
                service_name,
                service_definition,
                service_version,
                odata_info_uri,
                odata_version,
                is_published,
            ),
            "reading OData service information",
        )

    async def data_preview(
        self,
        user: UserContext,
        action: str,
        object_name: str | None = None,
        top: int = 100,
        select_fields: str | None = None,
        filter: str | None = None,
        orderby: str | None = None,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_data_preview",
            lambda connector: connector.data_preview(action, object_name, top, select_fields, filter, orderby),
            "previewing ABAP data",
        )

    async def cds_analysis(
        self,
        user: UserContext,
        action: str,
        object_type: str = "DDLS",
        object_name: str | None = None,
        relation_type: str = "network",
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_cds_analysis",
            lambda connector: connector.cds_analysis(action, object_type, object_name, relation_type),
            "analysing CDS view",
        )

    async def code_assist(
        self,
        user: UserContext,
        action: str,
        object_type: str,
        object_name: str | None = None,
        source: str | None = None,
        position: str | None = None,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_code_assist",
            lambda connector: connector.code_assist(action, object_type, object_name, source, position),
            "assisting ABAP code",
        )

    async def execute(
        self,
        user: UserContext,
        action: str,
        object_name: str,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._write_operation(
            user,
            "abap_execute",
            lambda connector: connector.execute(action, object_name, parameters),
            "executing ABAP program/class",
        )

    async def call_function(
        self,
        user: UserContext,
        function_name: str,
        importing: dict[str, Any] | None = None,
        changing: dict[str, Any] | None = None,
        tables: dict[str, list[dict[str, Any]]] | None = None,
        destination: str | None = None,
        commit: bool = False,
    ) -> dict[str, Any]:
        return await self._write_operation(
            user,
            "abap_call_function",
            lambda connector: connector.call_function(
                function_name, importing, changing, tables, destination, commit
            ),
            "calling ABAP function module",
        )

    async def system_info(
        self,
        user: UserContext,
        action: str,
    ) -> dict[str, Any]:
        return await self._read_operation(
            user,
            "abap_system_info",
            lambda connector: connector.system_info(action),
            "reading ABAP system info",
        )

    # ── End of workflow operations ──────────────────────────────────────────

    async def _run_with_connector(
        self,
        user: UserContext,
        tool_name: str,
        operation: Callable[[AdtConnector], Awaitable[T]],
        *,
        expired_message: str | None = None,
        quality_action: str | None = None,
        write: bool = False,
    ) -> T:
        check_tool_whitelist(tool_name, self.allowed_tools)
        authorize_tool(user, tool_name, write=write)
        connector, _discovery = await self._authenticated_connector()
        try:
            return await operation(connector)
        except AuthorizationError as exc:
            if quality_action:
                raise self._quality_auth_error(quality_action) from exc
            if self.sessions.should_use_basic_auth():
                cause = str(exc)
                raise AuthorizationError(
                    f"Basic ADT authorization failed: {cause} "
                    "Check abap_dev configuration and user permissions."
                ) from exc
            raise self._login_required_error(
                expired_message or f"The saved SSO session expired while executing this operation."
            ) from exc

    async def _authenticated_connector(self) -> tuple[AdtConnector, dict[str, Any]]:
        try:
            session = self.sessions.authenticated_session()
        except ConfigError as exc:
            if self.config.auth_mode == "basic":
                raise AuthorizationError(
                    "Basic ADT credentials are not configured. Set abap_dev.username/password "
                    "or legacy communication_user/communication_password."
                ) from exc
            raise self._login_required_error("No usable local SSO session was found.") from exc

        connector = AdtConnector(self.config, session)
        try:
            discovery = await connector.discovery()
        except AuthorizationError as exc:
            if session.auth_mode == "basic":
                raise AuthorizationError(
                    "Basic ADT authentication failed. Check abap_dev.username/password "
                    "or legacy communication_user/communication_password, and confirm the SAP system allows Basic Auth for ADT."
                ) from exc
            raise self._login_required_error("The saved SSO session is not authorized or has expired.") from exc
        return connector, discovery

    def _login_required_error(self, reason: str) -> AuthorizationError:
        login_result = self.sessions.open_login_once("auto_login_required")
        opened_text = "Opened" if login_result.get("browser_opened") else "Already opened"
        return AuthorizationError(
            f"{reason} {opened_text} the ABAP ADT SSO login URL. Complete browser authentication, then retry the tool. "
            f"login_url={login_result['login_url']} session_path={login_result['session_path']}"
        )

    @staticmethod
    def _expired_message(action: str) -> str:
        return f"The saved SSO session expired while {action}."

    def _quality_auth_error(self, action: str) -> AuthorizationError:
        if self.sessions.should_use_basic_auth():
            return AuthorizationError(
                f"Basic ADT authentication failed while {action}. Check SAP_COM_0735 for ABAP Unit, "
                f"SAP_COM_0901 for ATC if applicable, and the configured user authorizations."
            )
        return self._login_required_error(f"The saved SSO session expired while {action}.")
