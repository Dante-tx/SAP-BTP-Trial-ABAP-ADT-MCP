from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import unquote, urlparse

from sap_mcp.connectors.adt_registry import ADT_PATH_REGISTRATIONS, AdtPathRegistration
from sap_mcp.connectors.official.constants import CREATABLE_ALIASES, CREATABLE_OBJECT_TYPES
from sap_mcp.errors import ValidationError


class OfficialBaseMixin:
    def _destination_id(self) -> str:
        host = urlparse(self.session.system_url).hostname or "default"
        match = re.search(r"\b([A-Z0-9]{3})\b", host.upper())
        return match.group(1) if match else "default"

    def _assert_destination(self, destination: str) -> None:
        if not destination or destination.strip():
            return
        raise ValidationError("destination is required")

    def _creatable_type(self, object_type: str) -> dict[str, Any]:
        details = CREATABLE_OBJECT_TYPES.get(self._creatable_type_id(object_type))
        if not details:
            raise ValidationError(f"Unsupported creatable object type: {object_type}")
        return details

    def _creatable_type_id(self, object_type: str) -> str:
        requested = object_type.upper()
        if requested in CREATABLE_OBJECT_TYPES:
            return requested
        return CREATABLE_ALIASES.get(requested, "")

    def _object_content(self, object_content: str) -> dict[str, Any]:
        try:
            content = json.loads(object_content)
        except json.JSONDecodeError as exc:
            raise ValidationError("objectContent must be a JSON object string") from exc
        if not isinstance(content, dict):
            raise ValidationError("objectContent must be a JSON object string")
        return content

    def _required_content(self, content: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = content.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        raise ValidationError(f"objectContent requires one of: {', '.join(keys)}")

    def _validate_object_name(self, name: str, max_len: int) -> None:
        if not name.strip():
            raise ValidationError("Object name is required")
        if len(name.strip()) > max_len:
            raise ValidationError(f"Object name exceeds maximum length {max_len}")

    def _json_or_text(self, value: str) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    def _parse_asx_data(self, text: str) -> dict[str, str]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return {"SHORT_TEXT": text.strip()}
        for element in root.iter():
            if self._xml_local_name(element.tag) == "DATA":
                return self._direct_child_texts(element)
        return {}

    def _direct_child_texts(self, element: ET.Element) -> dict[str, str]:
        return {
            self._xml_local_name(child.tag): (child.text or "").strip()
            for child in list(element)
            if child.text is not None or len(child) == 0
        }

    def _asx_body(self, data: dict[str, Any]) -> str:
        fields = "".join(f"<{key}>{self._xml_escape(str(value))}</{key}>" for key, value in data.items())
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">'
            f"<asx:values><DATA>{fields}</DATA></asx:values></asx:abap>"
        )

    def _coerce_adt_path(self, uri: str) -> str:
        value = uri.strip()
        parsed = urlparse(value)
        if parsed.scheme and parsed.path:
            value = parsed.path
        if "/sap/bc/adt/" in value and not value.startswith("/sap/bc/adt/"):
            value = value[value.index("/sap/bc/adt/") :]
        value = unquote(value.split("#", 1)[0].split("?", 1)[0])
        if not value.startswith("/sap/bc/adt/"):
            raise ValidationError("URI must contain an ADT /sap/bc/adt path")
        return value

    def _object_ref_from_any_uri(self, uri: str) -> dict[str, str]:
        path = self._coerce_adt_path(uri)
        for registration in ADT_PATH_REGISTRATIONS:
            name = self._match_registration_name(path, registration)
            if name:
                return {"type": registration.canonical_type, "name": name}
        raise ValidationError(f"Cannot infer ABAP object from URI: {uri}")

    def _match_registration_name(self, path: str, registration: AdtPathRegistration) -> str | None:
        if registration.canonical_type == "FUNC":
            match = re.match(r"^/sap/bc/adt/functions/groups/([^/]+)/fmodules/([^/]+)", path, re.IGNORECASE)
            if match:
                return f"{unquote(match.group(1)).upper()}/{unquote(match.group(2)).upper()}"
            return None
        prefix, _, _suffix = registration.root_template.partition("{name}")
        if not path.lower().startswith(prefix.lower()):
            return None
        name = path[len(prefix) :].split("/", 1)[0]
        return unquote(name).upper() if name else None
