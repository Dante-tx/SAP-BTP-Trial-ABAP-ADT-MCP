from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from sap_mcp.connectors.core.registry import AdtResponse
from sap_mcp.errors import SapBackendError, ValidationError


_INCLUDE_MARKER_RE = re.compile(
    r'^\$ADT\s+include:\s+(?P<include_type>definitions|implementations|macros|testclasses)',
    re.IGNORECASE,
)


_VERSION_KEYS = ("active", "inactive")
_INCL_FALLBACK_TYPES = frozenset({"PROG", "FUGR"})


def _detect_include_type_from_source(source: str) -> str | None:
    """Detect include_type from '$ADT include:' marker in source first line."""
    first_line = source.split("\n", 1)[0] if source else ""
    if not first_line:
        return None
    match = _INCLUDE_MARKER_RE.match(first_line.strip())
    if match:
        return match.group("include_type").lower()
    return None


def _normalize_abap_source(text: str | None) -> str | None:
    """Strip \\r\\n to \\n so downstream consumers never deal with ADT double-escaped line endings."""
    if text is None:
        return None
    return text.replace("\r\n", "\n")


class AdtSourceMixin:
    async def read_source(
        self,
        object_type: str | None = None,
        name: str | None = None,
        scope: str | None = None,
        include_type: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        # Normalize scope early for version detection
        normalized_scope = self._normalize_scope(scope) if scope else None
        version_scope = normalized_scope if normalized_scope in (*_VERSION_KEYS, "both") else None

        # For version scopes, treat path resolution like main scope
        resolve_scope = "main" if version_scope else normalized_scope

        name = await self._resolve_repository_object_name(object_type, name) if object_type and name and not uri else name

        target = self._resolve_source_target(object_type, name, resolve_scope, include_type, uri)

        def _version_path(base_uri: str, version: str | None) -> str:
            if version == "active":
                sep = "&" if "?" in base_uri else "?"
                return f"{base_uri}{sep}version=active"
            if version == "inactive":
                sep = "&" if "?" in base_uri else "?"
                return f"{base_uri}{sep}version=inactive"
            return base_uri

        if version_scope == "both":
            # Fetch both active and inactive versions
            # For DDLS, use the DDL activeobject endpoint for the compiled active version
            if target.object_type.upper() == "DDLS":
                active_path = _version_path(target.uri, "active")
                active_response = await self._request("GET", active_path, accept="text/plain, application/xml, */*")
                active_etag = self._normalized_etag(active_response.headers.get("etag"), active_response.content_type)
                active_roundtrippable = False
                active_writable_uri = None
                active_writable_etag = None
            else:
                active_path = _version_path(target.uri, None)
                active_response = await self._request("GET", active_path, accept="text/plain, application/xml, */*")
                active_etag = self._normalized_etag(active_response.headers.get("etag"), active_response.content_type)
                active_roundtrippable = target.round_trippable
                active_writable_uri = active_path if target.round_trippable else None
                active_writable_etag = active_etag if target.round_trippable else None

            inactive_path = _version_path(target.uri, "inactive")

            try:
                inactive_response = await self._request("GET", inactive_path, accept="text/plain, application/xml, */*")
                inactive_etag = self._normalized_etag(inactive_response.headers.get("etag"), inactive_response.content_type)
                inactive_source = inactive_response.text
            except SapBackendError:
                inactive_source = None
                inactive_etag = None

            result = {
                "object_type": target.object_type,
                "name": target.name,
                "scope": "both",
                "source_kind": "source",
                "round_trippable": False if target.object_type.upper() == "DDLS" else target.round_trippable,
                "include_type": target.include_type,
                "read_hint": "Active (compiled) CDS source is read-only." if target.object_type.upper() == "DDLS" else target.read_hint,
                "versions": {
                    "active": {
                        "source": _normalize_abap_source(active_response.text),
                        "uri": active_path,
                        "etag": active_etag,
                        "content_type": active_response.content_type,
                        "writable_uri": active_writable_uri,
                        "writable_etag": active_writable_etag,
                    },
                    "inactive": {
                        "source": _normalize_abap_source(inactive_source),
                        "uri": inactive_path,
                        "etag": inactive_etag,
                        "content_type": inactive_response.content_type if inactive_source else None,
                        "writable_uri": inactive_path if target.round_trippable and inactive_source else None,
                        "writable_etag": inactive_etag if target.round_trippable and inactive_source else None,
                    } if inactive_source else None,
                },
            }
            return result

        # Single version (active / inactive / main)
        path = _version_path(target.uri, normalized_scope if normalized_scope in _VERSION_KEYS else None)

        # For DDLS active scope, use the DDL activeobject endpoint to resolve
        # the compiled (active) source rather than the editor source
        if normalized_scope == "active" and target.object_type.upper() == "DDLS":
            active_path = _version_path(target.uri, "active")
            response = await self._request("GET", active_path, accept="text/plain, application/xml, */*")
            etag = self._normalized_etag(response.headers.get("etag"), response.content_type)
            return {
                "object_type": target.object_type,
                "name": target.name,
                "source": _normalize_abap_source(response.text),
                "source_kind": "source",
                "uri": active_path,
                "etag": etag,
                "content_type": response.content_type,
                "scope": "active",
                "include_type": target.include_type,
                "round_trippable": False,
                "writable_uri": None,
                "writable_etag": None,
                "read_hint": "Active (compiled) CDS source is read-only. Use scope=main to edit.",
            }

        try:
            response = await self._request("GET", path, accept="text/plain, application/xml, */*")
        except SapBackendError as error:
            if error.details.get("status_code") == 404 and target.object_type.upper() in _INCL_FALLBACK_TYPES:
                incl_target = self._resolve_source_target("INCL", name, scope, include_type, None)
                incl_path = incl_target.uri
                response = await self._request("GET", incl_path, accept="text/plain, application/xml, */*")
                target = incl_target
                path = incl_path
            else:
                raise
        etag = self._normalized_etag(response.headers.get("etag"), response.content_type)
        result = {
            "object_type": target.object_type,
            "name": target.name,
            "source": _normalize_abap_source(response.text),
            "source_kind": target.source_kind,
            "uri": path,
            "etag": etag,
            "content_type": response.content_type,
            "scope": normalized_scope or target.scope,
            "include_type": target.include_type,
            "round_trippable": target.round_trippable,
            "writable_uri": path if target.round_trippable else None,
            "writable_etag": etag if target.round_trippable else None,
        }
        if target.include_type:
            result["source_part"] = target.include_type
        if target.read_hint:
            result["read_hint"] = target.read_hint
        if self._is_oo_source_type(target.object_type) and target.source_kind == "source_with_includes":
            return await self._with_oo_source_includes(result, target.object_type, target.name, path, response)
        return result

    async def update_source(
        self,
        object_type: str | None,
        name: str | None,
        source: str,
        etag: str | None,
        reason: str,
        include_type: str | None = None,
        uri: str | None = None,
        transport_request_number: str | None = None,
    ) -> dict[str, Any]:
        self._assert_write_allowed(reason)
        # Auto-detect include_type from source marker if not explicitly provided
        detected_include = _detect_include_type_from_source(source) if not include_type else None
        resolved_include_type = include_type or detected_include

        # When source has $ADT include: marker, strip the marker line so only
        # the actual source content is sent to the backend.
        stripped_source = source
        if detected_include and not include_type:
            lines = source.split("\n", 1)
            stripped_source = lines[1] if len(lines) > 1 else ""

        requested_scope = "include" if resolved_include_type else None
        name = await self._resolve_repository_object_name(object_type, name) if object_type and name and not uri else name
        target = self._resolve_source_target(object_type, name, requested_scope, resolved_include_type, uri, for_write=True)
        if not target.round_trippable:
            raise ValidationError(
                "This source target is read-only or not directly writable through abap_update_source. "
                f"{target.read_hint or ''}".strip()
            )
        await self._assert_object_write_allowed(target.object_type, target.name)
        path = target.uri
        content_type = "application/xml; charset=utf-8" if self._is_metadata_write_path(path) else "text/plain; charset=utf-8"
        request_etag = await self._update_request_etag(path, content_type, etag)
        etag_source = "provided" if etag else "auto_read"

        try:
            response, etag_source = await self._retry_on_etag_conflict(
                "PUT", path,
                params=self._update_corrnr_params(transport_request_number),
                content=stripped_source.encode("utf-8"),
                headers={"Content-Type": content_type},
                accept="application/xml, text/plain, */*",
                initial_etag=request_etag,
                initial_etag_source=etag_source,
            )
        except SapBackendError as error:
            raise self._augment_update_error(error, target) from error
        response_etag = self._normalized_etag(response.headers.get("etag"), response.content_type)
        return {
            "updated": True,
            "object_type": target.object_type,
            "name": target.name,
            "uri": path,
            "include_type": target.include_type,
            "status_code": response.status_code,
            "etag": response_etag,
            "writable_uri": path,
            "writable_etag": response_etag,
            "etag_source": etag_source,
        }

    def _update_corrnr_params(self, transport_request_number: str | None) -> dict[str, str] | None:
        request_number = (transport_request_number or "").strip().upper()
        return {"corrNr": request_number} if request_number else None

    async def _source_etag(self, source_path: str) -> str | None:
        try:
            response = await self._request("GET", source_path, accept="text/plain, */*")
            return self._normalized_etag(response.headers.get("etag"), response.content_type)
        except SapBackendError as error:
            if error.details.get("status_code") != 404:
                raise
            return None

    async def _update_request_etag(self, path: str, content_type: str, etag: str | None) -> str:
        if etag:
            return self._normalized_etag(etag, content_type) or etag
        response = await self._request("GET", path, accept="text/plain, application/xml, application/*, */*")
        return self._normalized_etag(response.headers.get("etag"), response.content_type) or "*"

    async def _with_oo_source_includes(
        self,
        result: dict[str, Any],
        object_type: str,
        name: str,
        main_path: str,
        main_response: AdtResponse,
    ) -> dict[str, Any]:
        if self._oo_source_part(object_type) != "source/main":
            result["source_part"] = main_path.rsplit("/", 1)[-1]
            return result
        try:
            includes = await self._oo_source_includes(object_type, name)
        except (SapBackendError, ET.ParseError, OSError):
            return result
        parts = [
            {
                "include_type": "main",
                "uri": main_path,
                "source": _normalize_abap_source(main_response.text),
                "etag": main_response.headers.get("etag"),
                "content_type": main_response.content_type,
                "scope": "main",
                "source_kind": "source",
                "round_trippable": True,
                "writable_uri": main_path,
                "writable_etag": main_response.headers.get("etag"),
            }
        ]
        for include in includes:
            if include["uri"] == main_path:
                continue
            try:
                include_response = await self._request("GET", include["uri"], accept="text/plain, */*")
            except (SapBackendError, OSError):
                continue
            parts.append({
                **include,
                "source": _normalize_abap_source(include_response.text),
                "etag": include_response.headers.get("etag", include.get("etag")),
                "content_type": include_response.content_type,
                "scope": "include",
                "source_kind": "source",
                "round_trippable": True,
                "writable_uri": include["uri"],
                "writable_etag": include_response.headers.get("etag", include.get("etag")),
            })
        if len(parts) == 1:
            return result
        result["source_kind"] = "source_with_includes"
        result["scope"] = "with_includes"
        result["round_trippable"] = False
        result["writable_uri"] = None
        result["writable_etag"] = None
        result["read_hint"] = self._build_read_hint(result["object_type"], result["name"], "include", "implementations")
        result["source_parts"] = parts
        result["includes"] = [
            {key: value for key, value in part.items() if key != "source"}
            for part in parts if part["include_type"] != "main"
        ]
        result["source"] = "\n\n".join(self._format_source_part(part) for part in parts if part.get("source", "").strip())
        return result

    async def _oo_source_includes(self, object_type: str, name: str) -> list[dict[str, Any]]:
        normalized_type = object_type.lower().split("/", 1)[0]
        collection = "interfaces" if normalized_type in {"interface", "intf"} else "classes"
        object_path = f"{ADT_BASE_PATH}/oo/{collection}/{quote(name.lower())}"
        metadata = await self._request(
            "GET",
            object_path,
            accept="application/vnd.sap.adt.oo.classes.v4+xml, application/vnd.sap.adt.oo.interfaces.v2+xml, application/xml, */*",
        )
        root = ET.fromstring(metadata.text)
        includes: list[dict[str, Any]] = []
        for element in root.iter():
            include_type = element.attrib.get("{http://www.sap.com/adt/oo/classes}includeType")
            if include_type is None:
                include_type = element.attrib.get("{http://www.sap.com/adt/oo/interfaces}includeType")
            if not include_type:
                continue
            for link in element.findall("{http://www.w3.org/2005/Atom}link"):
                if link.attrib.get("type") != "text/plain":
                    continue
                rel = link.attrib.get("rel", "")
                if not rel.endswith("/source"):
                    continue
                href = link.attrib.get("href")
                if not href:
                    continue
                includes.append({
                    "include_type": include_type,
                    "uri": self._adt_relative_url(f"{object_path.rstrip('/')}/", href),
                    "etag": self._normalized_etag(link.attrib.get("etag"), link.attrib.get("type")),
                })
        order = {"main": 0, "definitions": 1, "implementations": 2, "macros": 3, "testclasses": 4}
        return sorted(includes, key=lambda item: order.get(item["include_type"], 99))

    def _format_source_part(self, part: dict[str, Any]) -> str:
        include_type = part["include_type"]
        source = part.get("source", "")
        if include_type == "main":
            return source
        return f'"$ADT include: {include_type} ({part["uri"]})\n{source}'
