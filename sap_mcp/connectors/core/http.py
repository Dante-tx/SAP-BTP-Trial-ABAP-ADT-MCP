from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html import unescape
from typing import Any

import httpx

from sap_mcp.connectors.core.constants import (
    ADT_SESSION_CONTEXT_COOKIE_PREFIXES,
    ADT_SESSION_HEADER,
    ADT_SESSION_STATEFUL,
    ADT_SESSION_STATELESS,
    MAX_ETAG_RETRIES,
)
from sap_mcp.connectors.core.registry import ADT_ACCEPT, ADT_BASE_PATH, USER_AGENT, AdtResponse
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
            "User-Agent": USER_AGENT,
            **self._reentrance_headers(),
            **self.session.headers,
            **self._adt_session_headers(headers),
            **(headers or {}),
        }
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            merged_headers.setdefault("X-CSRF-Token", await self._csrf_token())

        async with httpx.AsyncClient(timeout=self.config.default_timeout_seconds, cookies=self._request_cookies(merged_headers)) as client:
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
                f'SAP redirected to {location}; run abap_adt_session(action="login") again.'
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
        discovery_path = f"{ADT_BASE_PATH}/discovery"
        request_headers = {
            "X-CSRF-Token": "Fetch",
            "Accept": ADT_ACCEPT,
            **self._reentrance_headers(),
            **self.session.headers,
            **self._adt_session_headers(),
        }
        async with httpx.AsyncClient(timeout=self.config.default_timeout_seconds, cookies=self._request_cookies(request_headers)) as client:
            response = await client.get(
                f"{self.session.system_url.rstrip('/')}{discovery_path}",
                params=self._client_params(),
                headers=request_headers,
                follow_redirects=False,
            )
            self._merge_cookies(client.cookies)
        self._persist_session_cookies()
        if response.status_code in {301, 302, 303, 307, 308}:
            raise AuthorizationError("Cannot fetch ADT CSRF token; SAP redirected to SSO login")
        if response.status_code >= 400:
            self._raise_for_error_response(response, "GET", discovery_path)
        token = response.headers.get("x-csrf-token")
        if not token:
            raise SapBackendError(
                "ADT did not return an X-CSRF-Token",
                details={
                    "category": "csrf_token",
                    "status_code": response.status_code,
                    "method": "GET",
                    "path": discovery_path,
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
        # Add hint / fix_suggestion for common ADT errors
        error_info = self._error_info(category, response.status_code, method, path)
        if error_info:
            details["hint"] = error_info["hint"]
            details["fix_suggestion"] = error_info["fix_suggestion"]
        html_summary = self._html_error_summary(response.text, details["content_type"])
        if html_summary:
            details["html_summary"] = html_summary
        if headers.get("x-csrf-token"):
            details["csrf_token_header"] = headers["x-csrf-token"]
        if category == "etag_conflict":
            server_etag = self._server_etag_from_precondition(message_text)
            if server_etag:
                details["server_etag"] = server_etag
        return details

    # ── Configuration-driven error hints (category, status_code, path_prefix) → (hint, fix_suggestion) ──
    # hint: Chinese for human readers; fix_suggestion: English for AI Agent parsing
    _ERROR_HINTS: tuple[dict[str, Any], ...] = (
        {"category": "authorization", "status_code": 403, "path_prefix": "/abapunit/",
         "hint": "ABAP Unit test授权不足，请在ABAP系统中为当前用户授予S_DEVELOP或对应ADT服务权限",
         "fix_suggestion": "Grant the current user S_DEVELOP or the required ADT service authorization in the ABAP system for ABAP Unit tests"},
        {"category": "authorization", "status_code": 403, "path_prefix": "/atc/",
         "hint": "ATC检查授权不足，请在ABAP系统中为当前用户授予S_DEVELOP或对应ADT服务权限",
         "fix_suggestion": "Grant the current user S_DEVELOP or the required ADT service authorization in the ABAP system for ATC checks"},
        {"category": "authorization", "status_code": 403, "path_prefix": None,
         "hint": "ADT授权不足，请检查ABAP系统中当前用户的S_DEVELOP或对应ADT服务权限",
         "fix_suggestion": "Check that the current SAP user has S_DEVELOP or required ADT service authorizations"},
        {"category": "sap_backend_message", "status_code": 404, "path_prefix": "/businessservices/bindings/",
         "hint": "服务绑定不存在或名称不精确（不支持通配符），请先通过abap_find_objects(object_type='SRVB')查找精确的绑定名称",
         "fix_suggestion": "Service binding not found; use abap_find_objects(object_type='SRVB') to find the exact binding name (wildcards are not supported)"},
        {"category": "sap_backend_message", "status_code": 404, "path_prefix": None,
         "hint": "对象不存在或路径不正确，请检查对象名称是否精确",
         "fix_suggestion": "Check the object name and path; the requested resource does not exist"},
        {"status_code": 412, "path_prefix": None,
         "hint": "ETag冲突，请重新读取对象获取最新的ETag后重试，或省略etag参数让工具自动处理",
         "fix_suggestion": "Re-read the object to obtain the latest ETag, then retry; or omit the etag parameter for auto-handling"},
        {"status_code": 404, "path_prefix": None,
         "hint": "请求的资源不存在，请检查URL路径或参数是否正确",
         "fix_suggestion": "The requested resource was not found; verify the URL path and parameters"},
        {"status_code": 500, "path_prefix": None, "status_code_min": True,
         "hint": "ADT后端服务器错误，可能是对象依赖不完整或系统内部错误，请检查前置依赖对象是否已创建",
         "fix_suggestion": "ADT backend server error; check if prerequisite objects are created, or investigate the SAP system logs"},
    )

    def _error_info(self, category: str, status_code: int, method: str, path: str) -> dict[str, str] | None:
        """Return {hint, fix_suggestion} for a given error context.

        Matches rules in priority order: more specific rules first.
        """
        for rule in self._ERROR_HINTS:
            if rule.get("category") and rule["category"] != category:
                continue
            if rule.get("status_code_min"):
                if status_code < rule["status_code"]:
                    continue
            elif rule.get("status_code") and rule["status_code"] != status_code:
                continue
            if rule.get("path_prefix") and rule["path_prefix"] not in path:
                continue
            return {"hint": rule["hint"], "fix_suggestion": rule.get("fix_suggestion", rule["hint"])}
        return None

    def _error_hint(self, status_code: int, category: str, method: str, path: str) -> str | None:
        """Return a human-readable hint for common ADT error patterns. (kept for backward compat)"""
        info = self._error_info(category, status_code, method, path)
        return info["hint"] if info else None

    def _classify_error(self, status_code: int, headers: dict[str, str], message_text: str) -> str:
        text = message_text.casefold()
        content_type = headers.get("content-type", "").casefold()
        if status_code >= 500 and ("text/html" in content_type or text.lstrip().startswith("<!doctype html")):
            return "sap_backend_html_error"
        csrf_header = headers.get("x-csrf-token", "").casefold()
        if csrf_header == "required" or "x-csrf-token" in text or text.startswith("csrf"):
            return "csrf_token"
        if status_code == 412 or status_code == 409:
            return "etag_conflict"
        if "if-match" in text or "etag" in text or "precondition" in text:
            return "etag_conflict"
        if status_code == 401:
            return "session_expired"
        if status_code == 403:
            # Match structured session-expired messages precisely, avoiding false positives
            if any(marker in text for marker in ("session expired", "session has expired", "logon required", "login required", "sso required")):
                return "session_expired"
            return "authorization"
        if text.strip():
            return "sap_backend_message"
        return "http_error"

    def _format_authorization_error(self, details: dict[str, Any]) -> str:
        hint = 'run abap_adt_session(action="login") again' if details["category"] == "session_expired" else "check SAP backend authorizations"
        return (
            f"ADT {details['category']} {details['status_code']} "
            f"{details['method']} {details['path']}: {self._sap_message_text(details['sap_messages'], details['raw_excerpt'])[:500]}. "
            f"{hint}."
        )

    def _format_backend_error(self, details: dict[str, Any]) -> str:
        text = details.get("html_summary") or self._sap_message_text(details["sap_messages"], details["raw_excerpt"])[:500]
        suffix = f" server_etag={details['server_etag']}" if details.get("server_etag") else ""
        hint = details.get("hint")
        hint_suffix = f" hint={hint}" if hint else ""
        return (
            f"ADT {details['category']} {details['status_code']} "
            f"{details['method']} {details['path']}: {text}{suffix}{hint_suffix}"
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

    def _adt_session_headers(self, explicit_headers: dict[str, str] | None = None) -> dict[str, str]:
        if any(key.casefold() == ADT_SESSION_HEADER.casefold() for key in (explicit_headers or {})):
            return {}
        session_type = getattr(self, "_adt_session_type", ADT_SESSION_STATELESS)
        return {ADT_SESSION_HEADER: session_type}

    def _set_adt_session_type(self, session_type: str) -> None:
        if session_type not in {ADT_SESSION_STATEFUL, ADT_SESSION_STATELESS}:
            raise ValueError(f"Unsupported ADT session type: {session_type}")
        self._adt_session_type = session_type

    async def _restore_stateless_session(self) -> None:
        self._set_adt_session_type(ADT_SESSION_STATELESS)
        try:
            await self._request(
                "GET",
                f"{ADT_BASE_PATH}/discovery",
                headers={ADT_SESSION_HEADER: ADT_SESSION_STATELESS},
                accept="application/xml, */*",
            )
        except SapBackendError:
            pass
        finally:
            self._drop_adt_session_context_cookies()
            self._persist_session_cookies()

    def _drop_adt_session_context_cookies(self) -> None:
        stale_names = [
            name for name in self.session.cookies
            if name.casefold().startswith(ADT_SESSION_CONTEXT_COOKIE_PREFIXES)
        ]
        for name in stale_names:
            self.session.cookies.pop(name, None)

    def _request_cookies(self, headers: dict[str, str]) -> dict[str, str]:
        session_type = self._request_session_type(headers)
        if session_type == ADT_SESSION_STATEFUL:
            return self.session.cookies
        return {
            name: value for name, value in self.session.cookies.items()
            if not name.casefold().startswith(ADT_SESSION_CONTEXT_COOKIE_PREFIXES)
        }

    def _request_session_type(self, headers: dict[str, str]) -> str:
        for name, value in headers.items():
            if name.casefold() == ADT_SESSION_HEADER.casefold():
                return value.casefold()
        return getattr(self, "_adt_session_type", ADT_SESSION_STATELESS)

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
        session_path = getattr(self.config, "session_path", None)
        if not session_path or not session_path.exists() or not self.session.cookies:
            return
        import json

        data = json.loads(session_path.read_text(encoding="utf-8"))
        data["cookies"] = self.session.cookies
        session_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _server_etag_from_precondition(self, message: str) -> str | None:
        # ADT error messages use formats like:
        #   "... does not match the object ETag <value> in the server"
        #   "... server_etag=<value> target_uri=..."
        patterns = (
            r"does not match the object ETag ['\"]?(.+?)['\"]?(?=\.?\s(?:in the server|target_uri=|expected_etag_scope=|read_hint=)|$)",
            r"server_etag=['\"]?(.+?)['\"]?(?=\s(?:target_uri=|expected_etag_scope=|read_hint=)|$)",
            r"object ETag ['\"]?(.+?)['\"]?(?=\.?\s(?:in the server|target_uri=|expected_etag_scope=|read_hint=)|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, message, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip().strip("'\"")
        return None

    def _if_match_etag(self, etag: str | None) -> str:
        value = (etag or "*").strip()
        if value == "*" or value.startswith('"') or value.startswith("W/"):
            return value
        return f'"{value}"'

    async def _retry_on_etag_conflict(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        accept: str = ADT_ACCEPT,
        initial_etag: str | None = None,
        initial_etag_source: str | None = None,
        max_retries: int = MAX_ETAG_RETRIES,
    ) -> tuple[AdtResponse, str]:
        """Unified ETag 412 retry: attempt the request, retry up to MAX_ETAG_RETRIES times on 412.

        Returns (response, etag_source) where etag_source indicates how the etag was obtained.
        """
        # SAP ADT uses raw (unquoted) ETag values (see hana1909.http: If-Match: 20210220150417).
        # _if_match_etag wrapping with double-quotes per RFC 7232 breaks ADT's If-Match check.
        # Use request_etag directly; wildcard "*" is still valid.
        request_etag = initial_etag or "*"
        etag_source = initial_etag_source or ("provided" if initial_etag else "wildcard")
        merged_headers = dict(headers or {})
        merged_headers["If-Match"] = request_etag

        for attempt in range(max_retries + 1):
            try:
                response = await self._request(
                    method, path,
                    params=params,
                    content=content,
                    headers=merged_headers,
                    accept=accept,
                )
                return response, etag_source
            except SapBackendError as error:
                if error.details.get("category") != "etag_conflict" or attempt == max_retries:
                    raise
                server_etag = error.details.get("server_etag") or self._server_etag_from_precondition(str(error))
                if not server_etag:
                    continue
                # SAP ADT uses raw ETag; try raw first, then quoted as fallback
                if attempt == 0:
                    merged_headers["If-Match"] = server_etag
                    etag_source = "server_retry_raw"
                else:
                    merged_headers["If-Match"] = self._if_match_etag(server_etag)
                    etag_source = "server_retry_quoted"

        raise SapBackendError("Max ETag retries exceeded")

    def _normalized_etag(self, etag: str | None, content_type: str | None) -> str | None:
        if not etag:
            return etag
        full_type = (content_type or "").strip().lower()
        if ";" not in full_type:
            return etag
        base_type = full_type.split(";", 1)[0].strip()
        if not base_type or full_type in etag:
            return etag
        return etag.replace(base_type, full_type)

    def _html_error_summary(self, text: str, content_type: str) -> str | None:
        lower_type = (content_type or "").casefold()
        if "html" not in lower_type and not text.lstrip().casefold().startswith("<!doctype html"):
            return None
        title = self._first_html_tag_text(text, "title")
        heading = self._first_html_tag_text(text, "h1") or self._first_html_tag_text(text, "h2")
        detail = self._first_html_element_text_by_id(text, "msgText")
        parts = [part for part in (title, heading, detail) if part]
        return " | ".join(dict.fromkeys(parts)) or "SAP returned an HTML error page instead of structured ADT error details"

    def _first_html_tag_text(self, text: str, tag: str) -> str | None:
        match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return None
        value = re.sub(r"<[^>]+>", " ", match.group(1))
        value = unescape(re.sub(r"\s+", " ", value).strip())
        return value or None

    def _first_html_element_text_by_id(self, text: str, element_id: str) -> str | None:
        match = re.search(
            rf"<(?P<tag>[a-z0-9]+)[^>]*\bid=[\"']{re.escape(element_id)}[\"'][^>]*>(?P<body>.*?)</(?P=tag)>",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return None
        value = re.sub(r"<[^>]+>", " ", match.group("body"))
        value = unescape(re.sub(r"\s+", " ", value).strip())
        return value or None

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
