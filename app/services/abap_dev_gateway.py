from __future__ import annotations

from typing import Any

from app.auth.browser_sso import BrowserSsoSessionManager
from app.config import AbapDevConfig
from app.connectors.adt import AdtConnector
from app.security import UserContext, authorize_tool


class AbapDevGateway:
    def __init__(self, config: AbapDevConfig):
        self.config = config
        self.sessions = BrowserSsoSessionManager(config)

    def login(self, user: UserContext) -> dict[str, Any]:
        authorize_tool(user, "abap_adt_login")
        return self.sessions.open_login()

    def save_session(self, user: UserContext, cookies: dict[str, str], headers: dict[str, str] | None = None) -> dict[str, Any]:
        authorize_tool(user, "abap_save_sso_session", write=True)
        return self.sessions.save_session(cookies, headers)

    def save_cookie_header(self, user: UserContext, cookie_header: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        authorize_tool(user, "abap_save_sso_cookie_header", write=True)
        return self.sessions.save_cookie_header(cookie_header, headers)

    async def connect(self, user: UserContext) -> dict[str, Any]:
        authorize_tool(user, "abap_adt_connect")
        return await self._connector().discovery()

    async def search_objects(
        self,
        user: UserContext,
        query: str,
        max_results: int = 20,
        object_type: str | None = None,
        package: str | None = None,
    ) -> list[dict[str, Any]]:
        authorize_tool(user, "abap_search_objects")
        return await self._connector().search_objects(query, max_results, object_type, package)

    async def read_source(self, user: UserContext, object_type: str, name: str) -> dict[str, Any]:
        authorize_tool(user, "abap_read_source")
        return await self._connector().read_source(object_type, name)

    async def create_object(
        self,
        user: UserContext,
        object_type: str,
        name: str,
        package: str,
        description: str,
        reason: str,
        source: str | None = None,
    ) -> dict[str, Any]:
        authorize_tool(user, "abap_create_object", write=True)
        return await self._connector().create_object(object_type, name, package, description, reason, source)

    async def update_source(
        self,
        user: UserContext,
        object_type: str,
        name: str,
        source: str,
        etag: str,
        reason: str,
    ) -> dict[str, Any]:
        authorize_tool(user, "abap_update_source", write=True)
        return await self._connector().update_source(object_type, name, source, etag, reason)

    async def activate_object(self, user: UserContext, object_type: str, name: str, reason: str) -> dict[str, Any]:
        authorize_tool(user, "abap_activate_object", write=True)
        return await self._connector().activate_object(object_type, name, reason)

    async def delete_object(self, user: UserContext, object_type: str, name: str, reason: str) -> dict[str, Any]:
        authorize_tool(user, "abap_delete_object", write=True)
        return await self._connector().delete_object(object_type, name, reason)

    async def publish_service_binding(self, user: UserContext, name: str, reason: str) -> dict[str, Any]:
        authorize_tool(user, "abap_publish_service_binding", write=True)
        return await self._connector().publish_service_binding(name, reason)

    def _connector(self) -> AdtConnector:
        return AdtConnector(self.config, self.sessions.load_session())
