from __future__ import annotations

from typing import Any

from sap_mcp.connectors.core.registry import AdtResponse
from sap_mcp.connectors.objects.lock import LockMixin
from sap_mcp.errors import SapBackendError


class AdtDeleteMixin(LockMixin):
    async def delete_object(
        self,
        object_type: str,
        name: str,
        reason: str,
        etag: str | None = None,
        transport_request_number: str | None = None,
    ) -> dict[str, Any]:
        self._assert_write_allowed(reason)
        canonical_type = self._canonical_object_type(object_type)
        resolved_name = await self._resolve_repository_object_name(canonical_type, name)
        object_name = (resolved_name or name).strip().upper()
        await self._assert_object_write_allowed(canonical_type, object_name)
        uri = self._object_path(canonical_type, object_name)
        corrnr_params = self._delete_corrnr_params(transport_request_number)
        request_etag, etag_source = await self._delete_request_etag(canonical_type, object_name, uri, etag)
        active_uri = self._active_delete_path(uri)
        try:
            response = await self._request(
                "DELETE", uri,
                params=corrnr_params,
                headers={"If-Match": request_etag},
                accept="application/xml, text/plain, */*",
            )
        except SapBackendError as error:
            return await self._delete_after_initial_failure(canonical_type, object_name, uri, active_uri, error, corrnr_params)
        return self._delete_result(canonical_type, object_name, uri, response, etag_source, transport_request_number)

    async def _delete_after_initial_failure(
        self,
        canonical_type: str,
        object_name: str,
        uri: str,
        active_uri: str | None,
        error: SapBackendError,
        corrnr_params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        server_etag = error.details.get("server_etag") or self._server_etag_from_precondition(str(error))
        if server_etag:
            result = await self._delete_with_server_etag(canonical_type, object_name, uri, server_etag, corrnr_params)
            if result:
                return result
        try:
            response = await self._request(
                "DELETE", uri, params=corrnr_params, headers={"If-Match": "*"}, accept="application/xml, text/plain, */*",
            )
        except SapBackendError as wildcard_error:
            return await self._delete_after_wildcard_failure(canonical_type, object_name, uri, active_uri, wildcard_error, corrnr_params)
        return self._delete_result(canonical_type, object_name, uri, response, "wildcard_retry", corrnr_params=corrnr_params)

    async def _delete_after_wildcard_failure(
        self,
        canonical_type: str,
        object_name: str,
        uri: str,
        active_uri: str | None,
        wildcard_error: SapBackendError,
        corrnr_params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        wildcard_server_etag = wildcard_error.details.get("server_etag") or self._server_etag_from_precondition(str(wildcard_error))
        if wildcard_server_etag:
            result = await self._delete_with_server_etag(canonical_type, object_name, uri, wildcard_server_etag, corrnr_params)
            if result:
                return result
            lock_result = await self._delete_with_lock_handle(canonical_type, object_name, uri, corrnr_params)
            if lock_result:
                return lock_result
            raise wildcard_error
        if not active_uri:
            raise wildcard_error
        response = await self._request(
            "DELETE", active_uri, params=corrnr_params, headers={"If-Match": "*"}, accept="application/xml, text/plain, */*",
        )
        return self._delete_result(canonical_type, object_name, uri, response, "active_endpoint", corrnr_params=corrnr_params)

    async def _delete_with_lock_handle(
        self,
        canonical_type: str,
        object_name: str,
        uri: str,
        corrnr_params: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        handle = await self._try_lock(uri)
        if not handle:
            return None
        try:
            params = {"lockHandle": handle, **(corrnr_params or {})}
            response = await self._request(
                "DELETE", uri, params=params,
                headers=self._stateful_headers(),
                accept="application/xml, text/plain, */*",
            )
        except SapBackendError:
            await self._unlock_object(uri, handle)
            return None
        await self._restore_stateless_session()
        return self._delete_result(canonical_type, object_name, uri, response, "lock_handle", corrnr_params=corrnr_params)

    async def _try_lock(self, uri: str) -> str | None:
        try:
            return await self._lock_object(uri)
        except SapBackendError:
            return None

    async def _delete_with_server_etag(
        self,
        canonical_type: str,
        object_name: str,
        uri: str,
        server_etag: str,
        corrnr_params: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        for retry_etag, etag_source in self._delete_etag_candidates(server_etag):
            try:
                response = await self._request(
                    "DELETE", uri, params=corrnr_params, headers={"If-Match": retry_etag},
                    accept="application/xml, text/plain, */*",
                )
                return self._delete_result(canonical_type, object_name, uri, response, etag_source, corrnr_params=corrnr_params)
            except SapBackendError:
                pass
        return None

    def _delete_etag_candidates(self, server_etag: str) -> list[tuple[str, str]]:
        raw_etag = server_etag.strip()
        quoted_etag = self._if_match_etag(raw_etag)
        candidates = [(raw_etag, "server_retry")]
        if quoted_etag != raw_etag:
            candidates.append((quoted_etag, "server_retry_quoted"))
        return candidates

    def _delete_result(
        self,
        canonical_type: str,
        name: str,
        uri: str,
        response: AdtResponse,
        etag_source: str,
        transport_request_number: str | None = None,
        corrnr_params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        result = {
            "deleted": True, "object_type": canonical_type, "name": name, "uri": uri,
            "status_code": response.status_code, "etag_source": etag_source,
        }
        request_number = transport_request_number or (corrnr_params or {}).get("corrNr")
        if request_number:
            result["transport_request_number"] = request_number.strip().upper()
        return result

    def _delete_corrnr_params(self, transport_request_number: str | None) -> dict[str, str] | None:
        request_number = (transport_request_number or "").strip().upper()
        return {"corrNr": request_number} if request_number else None

    def _active_delete_path(self, uri: str) -> str | None:
        idx = uri.find("/sources/")
        return None if idx == -1 else uri[:idx] + uri[idx + len("/sources"):]

    async def _delete_request_etag(self, object_type: str, name: str, uri: str, etag: str | None) -> tuple[str, str]:
        if etag:
            return etag, "provided"
        try:
            metadata = await self._request("GET", uri, accept="application/xml, application/*, */*")
            metadata_etag = self._normalized_etag(metadata.headers.get("etag"), metadata.content_type)
            if metadata_etag:
                return metadata_etag, "metadata"
        except SapBackendError:
            pass
        registration = self._find_path_registration(object_type)
        if registration and getattr(registration, 'source_suffix', None):
            try:
                source_etag = await self._source_etag(self._source_path(object_type, name))
                if source_etag:
                    return source_etag, "source"
            except SapBackendError:
                pass
        return "*", "wildcard"
