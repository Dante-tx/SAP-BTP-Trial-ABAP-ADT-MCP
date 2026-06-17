from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

from sap_mcp.connectors.official.base import OfficialBaseMixin
from sap_mcp.connectors.official.constants import (
    GENERATOR_ACCEPT,
    GENERATOR_ALIASES,
    GENERATOR_CONTENT_ACCEPT,
    GENERATOR_CONTENT_TYPE,
    GENERATOR_DESCRIPTIONS,
    GENERATOR_SCHEMA_ACCEPT,
)
from sap_mcp.errors import ValidationError


class GeneratorsMixin(OfficialBaseMixin):
    async def generators_list_generators(self, destination: str) -> dict[str, Any]:
        self._assert_destination(destination)
        return {"generators": [{"id": generator_id, **data} for generator_id, data in GENERATOR_DESCRIPTIONS.items()]}

    async def generators_get_schema(
        self,
        destination: str,
        generator_id: str,
        package_name: str,
        referenced_object_type: str,
        referenced_object_name: str,
    ) -> dict[str, Any]:
        self._assert_destination(destination)
        normalized_generator = self._generator_id(generator_id)
        ref_uri = self._generator_reference_uri(referenced_object_type, referenced_object_name)
        params = {"referencedObject": ref_uri, "package": package_name}
        schema_response = await self._request(
            "GET",
            f"/sap/bc/adt/businessservices/generators/{normalized_generator}/schema",
            params=params,
            accept=GENERATOR_SCHEMA_ACCEPT,
        )
        content_response = await self._request(
            "GET",
            f"/sap/bc/adt/businessservices/generators/{normalized_generator}/content",
            params=params,
            accept=GENERATOR_CONTENT_ACCEPT,
        )
        return {"schema": self._json_or_text(schema_response.text), "referenceContent": self._json_or_text(content_response.text)}

    async def generators_generate_objects(
        self,
        destination: str,
        generator_id: str,
        content: str,
        package_name: str,
        transport_request_number: str,
        referenced_object_type: str,
        referenced_object_name: str,
    ) -> dict[str, Any]:
        self._assert_destination(destination)
        self._assert_write_allowed("Generate RAP objects through ADT-compatible generator workflow")
        if package_name.upper() != "$TMP":
            self._assert_package_allowed(package_name)
        normalized_generator = self._generator_id(generator_id)
        ref_uri = self._generator_reference_uri(referenced_object_type, referenced_object_name)
        payload = self._json_or_text(content)
        if not isinstance(payload, dict):
            raise ValidationError("content must be a JSON object string")
        payload.setdefault("metadata", {})
        if isinstance(payload["metadata"], dict):
            payload["metadata"].setdefault("package", package_name)

        validation = await self._request(
            "POST",
            f"/sap/bc/adt/businessservices/generators/{normalized_generator}/validation",
            params={"referencedObject": ref_uri},
            content=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": GENERATOR_CONTENT_TYPE},
            accept="application/vnd.sap.as+xml, application/xml, */*",
        )
        validation_message = self._parse_generator_validation(validation.text)
        if validation_message.get("severity") == "error":
            return {"validationMessages": [validation_message], "generatedObjects": [], "error": validation_message["shortText"]}

        response = await self._request(
            "POST",
            f"/sap/bc/adt/businessservices/generators/{normalized_generator}",
            params={"referencedObject": ref_uri, "corrNr": transport_request_number or ""},
            content=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": GENERATOR_CONTENT_TYPE},
            accept=GENERATOR_ACCEPT,
        )
        return {
            "validationMessages": [] if not validation_message.get("shortText") else [validation_message],
            "generatedObjects": self._parse_object_references(response.text),
            "error": None,
        }

    def _generator_id(self, generator_id: str) -> str:
        normalized = GENERATOR_ALIASES.get(generator_id.strip().lower())
        if not normalized:
            raise ValidationError(f"Unsupported RAP generator: {generator_id}")
        return normalized

    def _generator_reference_uri(self, referenced_object_type: str, referenced_object_name: str) -> str:
        if not referenced_object_type.strip() or not referenced_object_name.strip():
            return ""
        return self._object_path(referenced_object_type, referenced_object_name)

    def _parse_generator_validation(self, text: str) -> dict[str, str]:
        record = self._parse_asx_data(text)
        return {
            "severity": (record.get("SEVERITY") or "ok").lower(),
            "shortText": record.get("SHORT_TEXT") or "",
            "longText": record.get("LONG_TEXT") or "",
        }

    def _parse_object_references(self, text: str) -> list[dict[str, str]]:
        refs = []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return refs
        for element in root.iter():
            if self._xml_local_name(element.tag) != "objectReference":
                continue
            attrs = {self._xml_local_name(key): value for key, value in element.attrib.items()}
            refs.append(
                {
                    "objectName": attrs.get("name", ""),
                    "objectType": attrs.get("type", ""),
                    "uri": attrs.get("uri", ""),
                    "description": attrs.get("description", ""),
                }
            )
        return refs
