from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from sap_mcp.connectors.adt_registry import ADT_ACCEPT, AdtResponse
from sap_mcp.errors import AuthorizationError, SapBackendError


class AdtHttpMixin:
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        accept: str = ADT_ACCEPT,
        content: bytes | None = None,
    ) -> AdtResponse:
        merged_headers = {
            "Accept": accept,
            "User-Agent": "sap-mcp-adt/0.1",
            **self._reentrance_headers(),
            **self.session.headers,
            **(headers or {}),
        }
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            merged_headers.setdefault("X-CSRF-Token", await self._csrf_token())

        async with httpx.AsyncClient(timeout=self.config.default_timeout_seconds, cookies=self.session.cookies) as client:
            response = await client.request(
                method,
                f"{self.session.system_url.rstrip('/')}/{path.lstrip('/')}",
                params=self._client_params(params),
                headers=merged_headers,
                content=content,
                follow_redirects=False,
            )
            self._merge_cookies(client.cookies)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location", "SSO login")
            raise AuthorizationError(
                "ADT session is not authorized or has expired. "
                f"SAP redirected to {location}; run abap_adt_login again."
            )
        if response.status_code >= 400:
            self._raise_for_error_response(response, method, path)
        return AdtResponse(
            status_code=response.status_code,
            text=response.text,
            headers=dict(response.headers),
            content_type=response.headers.get("content-type", ""),
        )

    async def _csrf_token(self) -> str:
        async with httpx.AsyncClient(timeout=self.config.default_timeout_seconds, cookies=self.session.cookies) as client:
            response = await client.get(
                f"{self.session.system_url.rstrip('/')}/sap/bc/adt/discovery",
                params=self._client_params(),
                headers={"X-CSRF-Token": "Fetch", "Accept": ADT_ACCEPT, **self._reentrance_headers(), **self.session.headers},
                follow_redirects=False,
            )
            self._merge_cookies(client.cookies)
        self._persist_session_cookies()
        if response.status_code in {301, 302, 303, 307, 308}:
            raise AuthorizationError("Cannot fetch ADT CSRF token; SAP redirected to SSO login")
        if response.status_code >= 400:
            self._raise_for_error_response(response, "GET", "/sap/bc/adt/discovery")
        token = response.headers.get("x-csrf-token")
        if not token:
            raise SapBackendError(
                "ADT did not return an X-CSRF-Token",
                details={
                    "category": "csrf_token",
                    "status_code": response.status_code,
                    "method": "GET",
                    "path": "/sap/bc/adt/discovery",
                    "content_type": response.headers.get("content-type", ""),
                    "sap_messages": self._parse_status_messages(response.text),
                    "raw_excerpt": response.text[:500],
                },
            )
        return token

    def _raise_for_error_response(self, response: httpx.Response, method: str, path: str) -> None:
        details = self._sap_error_details(response, method, path)
        if details["category"] == "session_expired":
            raise AuthorizationError(self._format_authorization_error(details))
        raise SapBackendError(self._format_backend_error(details), details=details)

    def _sap_error_details(self, response: httpx.Response, method: str, path: str) -> dict[str, Any]:
        messages = self._parse_status_messages(response.text)
        message_text = self._sap_message_text(messages, response.text)
        headers = {key.lower(): value for key, value in response.headers.items()}
        category = self._classify_error(response.status_code, headers, message_text)
        details: dict[str, Any] = {
            "category": category,
            "status_code": response.status_code,
            "method": method.upper(),
            "path": path,
            "content_type": response.headers.get("content-type", ""),
            "sap_messages": messages,
            "raw_excerpt": response.text[:500],
        }
        if headers.get("x-csrf-token"):
            details["csrf_token_header"] = headers["x-csrf-token"]
        if category == "etag_conflict":
            server_etag = self._server_etag_from_precondition(message_text)
            if server_etag:
                details["server_etag"] = server_etag
        return details

    def _classify_error(self, status_code: int, headers: dict[str, str], message_text: str) -> str:
        text = message_text.casefold()
        if "csrf" in text or "x-csrf-token" in text or headers.get("x-csrf-token", "").casefold() == "required":
            return "csrf_token"
        if status_code == 412 or "if-match" in text or "etag" in text or "precondition" in text:
            return "etag_conflict"
        if status_code == 401:
            return "session_expired"
        if status_code == 403:
            if any(marker in text for marker in ("session", "expired", "logon", "login", "sso")):
                return "session_expired"
            return "authorization"
        if text.strip():
            return "sap_backend_message"
        return "http_error"

    def _format_authorization_error(self, details: dict[str, Any]) -> str:
        hint = "run abap_adt_login again" if details["category"] == "session_expired" else "check SAP backend authorizations"
        return (
            f"ADT {details['category']} {details['status_code']} "
            f"{details['method']} {details['path']}: {self._sap_message_text(details['sap_messages'], details['raw_excerpt'])[:500]}. "
            f"{hint}."
        )

    def _format_backend_error(self, details: dict[str, Any]) -> str:
        text = self._sap_message_text(details["sap_messages"], details["raw_excerpt"])[:500]
        suffix = f" server_etag={details['server_etag']}" if details.get("server_etag") else ""
        return (
            f"ADT {details['category']} {details['status_code']} "
            f"{details['method']} {details['path']}: {text}{suffix}"
        )

    def _sap_message_text(self, messages: list[dict[str, str]], fallback: str) -> str:
        parts: list[str] = []
        for message in messages:
            for key in ("code", "severity", "type", "shorttext", "message", "text"):
                value = message.get(key)
                if value and value not in parts:
                    parts.append(value)
        return " | ".join(parts) if parts else fallback.strip()

    def _reentrance_headers(self) -> dict[str, str]:
        params = self.session.reentrance
        if not params:
            return {}
        headers: dict[str, str] = {}
        for key in ("httpHeader", "http-header", "header"):
            value = params.get(key)
            if value and ":" in value:
                name, _, header_value = value.partition(":")
                headers[name.strip()] = header_value.strip()
        for key in ("reentranceTicket", "reentrance-ticket", "ticket", "assertionTicket", "assertion-ticket"):
            value = params.get(key)
            if value:
                headers.setdefault("MYSAPSSO2", value)
                headers.setdefault("x-sap-security-session", "create")
        return headers

    def _client_params(self, params: dict[str, str] | None = None) -> dict[str, str] | None:
        client = self.config.client
        if not client:
            return params
        merged = dict(params or {})
        merged.setdefault("sap-client", client)
        return merged

    def _merge_cookies(self, cookies: httpx.Cookies) -> None:
        for cookie in cookies.jar:
            self.session.cookies[cookie.name] = cookie.value

    def _persist_session_cookies(self) -> None:
        if not self.config.session_path.exists() or not self.session.cookies:
            return
        import json

        data = json.loads(self.config.session_path.read_text(encoding="utf-8"))
        data["cookies"] = self.session.cookies
        self.config.session_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _server_etag_from_precondition(self, message: str) -> str | None:
        patterns = (
            r"does not match the object ETag ([^\s<|]+)",
            r"server_etag=([^\s<|]+)",
            r"object ETag ['\"]?([^'\"\s<|]+)['\"]?",
        )
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    def _parse_status_messages(self, text: str) -> list[dict[str, str]]:
        if not text.strip():
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return [{"text": text.strip()}]
        messages: list[dict[str, str]] = []
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1].lower()
            if tag not in {"message", "statusmessage", "status", "error"}:
                continue
            item = {self._clean_xml_name(key).lower(): value for key, value in element.attrib.items()}
            if element.text and element.text.strip():
                item["text"] = element.text.strip()
            for child in element:
                child_tag = child.tag.rsplit("}", 1)[-1].lower()
                if child_tag in {"code", "message", "severity", "type", "shorttext", "longtext"}:
                    child_text = (child.text or "").strip()
                    if child_text:
                        item[child_tag] = child_text
            if item:
                messages.append(item)
        if messages:
            return messages

        root_item = {self._clean_xml_name(key).lower(): value for key, value in root.attrib.items()}
        for child in root:
            child_tag = child.tag.rsplit("}", 1)[-1].lower()
            if child_tag in {"code", "message", "severity", "type", "shorttext", "longtext"}:
                child_text = (child.text or "").strip()
                if child_text:
                    root_item[child_tag] = child_text
        if root_item:
            messages.append(root_item)
        return messages
