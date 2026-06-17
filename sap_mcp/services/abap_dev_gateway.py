from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sap_mcp.auth.browser_sso import BrowserSsoSessionManager
from sap_mcp.config import AbapDevConfig
from sap_mcp.connectors.adt import AdtConnector
from sap_mcp.errors import AuthorizationError, ConfigError
from sap_mcp.security import UserContext, authorize_tool
from sap_mcp.services.official_gateway import OfficialGatewayMixin


T = TypeVar("T")


class AbapDevGateway(OfficialGatewayMixin):
    def __init__(self, config: AbapDevConfig):
        self.config = config
        self.sessions = BrowserSsoSessionManager(config)

    async def login(self, user: UserContext) -> dict[str, Any]:
        authorize_tool(user, "abap_adt_login")
        return await self.sessions.login()

    def save_session(
        self, user: UserContext, cookies: dict[str, str], headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        authorize_tool(user, "abap_save_sso_session", write=True)
        return self.sessions.save_session(cookies, headers)

    def save_cookie_header(
        self, user: UserContext, cookie_header: str, headers: dict[str, str] | None = None
    ) -> dict[str, Any]:
        authorize_tool(user, "abap_save_sso_cookie_header", write=True)
        return self.sessions.save_cookie_header(cookie_header, headers)

    async def connect(self, user: UserContext) -> dict[str, Any]:
        authorize_tool(user, "abap_adt_connect")
        _connector, discovery = await self._authenticated_connector()
        return discovery

    async def search_objects(
        self,
        user: UserContext,
        query: str,
        max_results: int = 20,
        object_type: str | None = None,
        package: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._run_with_connector(
            user,
            "abap_search_objects",
            lambda connector: connector.search_objects(query, max_results, object_type, package),
            expired_message="The saved SSO session expired while searching ABAP objects.",
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
        return await self._run_with_connector(
            user,
            "abap_read_source",
            lambda connector: connector.read_source(object_type, name, scope, include_type, uri),
            expired_message="The saved SSO session expired while reading ABAP source.",
        )

    async def get_object_metadata(
        self,
        user: UserContext,
        object_type: str | None = None,
        name: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_get_object_metadata",
            lambda connector: connector.get_object_metadata(object_type, name, uri),
            expired_message="The saved SSO session expired while reading ABAP object metadata.",
        )

    async def create_object(
        self,
        user: UserContext,
        object_type: str,
        name: str,
        package: str,
        description: str,
        reason: str,
        source: str | None = None,
        service_binding_version: str | None = None,
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_create_object",
            lambda connector: connector.create_object(
                object_type,
                name,
                package,
                description,
                reason,
                source,
                service_binding_version,
            ),
            expired_message="The saved SSO session expired while creating the ABAP object.",
            write=True,
        )

    async def update_source(
        self,
        user: UserContext,
        object_type: str | None,
        name: str | None,
        source: str,
        etag: str,
        reason: str,
        include_type: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_update_source",
            lambda connector: connector.update_source(object_type, name, source, etag, reason, include_type, uri),
            expired_message="The saved SSO session expired while updating ABAP source.",
            write=True,
        )

    async def activate_object(self, user: UserContext, object_type: str, name: str, reason: str) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_activate_object",
            lambda connector: connector.activate_object(object_type, name, reason),
            expired_message="The saved SSO session expired while activating the ABAP object.",
            write=True,
        )

    async def activate_objects(self, user: UserContext, objects: list[dict[str, str]], reason: str) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_activate_objects",
            lambda connector: connector.activate_objects(objects, reason),
            expired_message="The saved SSO session expired while activating ABAP objects.",
            write=True,
        )

    async def delete_object(self, user: UserContext, object_type: str, name: str, reason: str) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_delete_object",
            lambda connector: connector.delete_object(object_type, name, reason),
            expired_message="The saved SSO session expired while deleting the ABAP object.",
            write=True,
        )

    async def publish_service_binding(
        self, user: UserContext, name: str, reason: str, odata_version: str | None = None
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_publish_service_binding",
            lambda connector: connector.publish_service_binding(name, reason, odata_version),
            expired_message="The saved SSO session expired while publishing the service binding.",
            write=True,
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
        return await self._run_with_connector(
            user,
            "abap_run_unit_tests",
            lambda connector: connector.run_unit_tests(objects, packages, include_subpackages, title, wait_seconds),
            quality_action="running ABAP Unit tests",
        )

    async def get_unit_test_run(self, user: UserContext, run_uri: str) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_get_unit_test_run",
            lambda connector: connector.get_unit_test_run(run_uri),
            quality_action="reading the ABAP Unit run",
        )

    async def get_unit_test_result(self, user: UserContext, result_uri: str) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_get_unit_test_result",
            lambda connector: connector.get_unit_test_result(result_uri),
            quality_action="reading the ABAP Unit result",
        )

    async def run_atc_checks(
        self,
        user: UserContext,
        objects: list[dict[str, str]] | None = None,
        packages: list[str] | None = None,
        include_subpackages: bool = False,
        check_variant: str | None = None,
        configuration: str | None = None,
        wait_seconds: int = 0,
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_run_atc_checks",
            lambda connector: connector.run_atc_checks(
                objects, packages, include_subpackages, check_variant, configuration, wait_seconds
            ),
            quality_action="running ATC checks",
        )

    async def get_atc_run(self, user: UserContext, run_uri: str) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_get_atc_run",
            lambda connector: connector.get_atc_run(run_uri),
            quality_action="reading the ATC run",
        )

    async def get_atc_result(self, user: UserContext, result_uri: str) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_get_atc_result",
            lambda connector: connector.get_atc_result(result_uri),
            quality_action="reading the ATC result",
        )

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
        authorize_tool(user, tool_name, write=write)
        connector, _discovery = await self._authenticated_connector()
        try:
            return await operation(connector)
        except AuthorizationError as exc:
            if quality_action:
                raise self._quality_auth_error(quality_action) from exc
            raise self._login_required_error(expired_message or "The saved SSO session expired.") from exc

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

    def _quality_auth_error(self, action: str) -> AuthorizationError:
        if self.sessions.should_use_basic_auth():
            return AuthorizationError(
                f"Basic ADT authentication failed while {action}. Check SAP_COM_0735 for ABAP Unit, "
                f"SAP_COM_0901 for ATC if applicable, and the configured user authorizations."
            )
        return self._login_required_error(f"The saved SSO session expired while {action}.")
