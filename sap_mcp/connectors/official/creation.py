from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

from sap_mcp.connectors.official.base import OfficialBaseMixin
from sap_mcp.connectors.official.constants import CREATABLE_OBJECT_TYPES
from sap_mcp.errors import SapBackendError


class CreationMixin(OfficialBaseMixin):
    async def creation_get_all_creatable_objects(self, destination: str) -> dict[str, Any]:
        self._assert_destination(destination)
        try:
            response = await self._request(
                "POST",
                "/sap/bc/adt/repository/typestructure",
                accept="application/vnd.sap.as+xml, application/xml, */*",
            )
            objects = self._parse_type_structure(response.text)
        except Exception:
            objects = []
        if not objects:
            objects = [
                {"name": item["name"], "objectType": object_type}
                for object_type, item in sorted(CREATABLE_OBJECT_TYPES.items())
            ]
        return {"creatableObjects": objects}

    async def creation_get_object_type_details(
        self,
        destination: str,
        object_type: str,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        self._assert_destination(destination)
        object_type_id = self._creatable_type_id(object_type)
        details = self._creatable_type(object_type)
        fields = [
            {"name": "name", "required": True, "value": name or "", "maxLength": details["max_len"]},
            {"name": "description", "required": True, "value": description or ""},
            {"name": "packageName", "required": True, "value": ""},
        ]
        if object_type_id == "FUGR/FF":
            fields.append({"name": "parentName", "required": True, "value": ""})
        if object_type_id == "SRVB/SVB":
            fields.extend(
                [
                    {"name": "serviceDefinition", "required": True, "value": ""},
                    {"name": "serviceBindingVersion", "required": False, "value": "ODATA\\V2"},
                ]
            )
        if object_type_id == "DEVC/K":
            fields.extend(
                [
                    {"name": "softwareComponent", "required": False, "value": ""},
                    {"name": "transportLayer", "required": False, "value": ""},
                    {"name": "packageType", "required": False, "value": "development"},
                ]
            )
        return {
            "objectType": object_type_id,
            "name": details["name"],
            "fields": fields,
            "recordingRequired": True,
        }

    async def creation_run_validation(self, destination: str, object_type: str, object_content: str) -> dict[str, Any]:
        self._assert_destination(destination)
        content = self._object_content(object_content)
        object_type_id = self._creatable_type_id(object_type)
        details = self._creatable_type(object_type)
        object_name = self._required_content(content, "name")
        description = self._required_content(content, "description")
        package_name = self._required_content(content, "packageName", "package", "developmentPackage")
        self._validate_object_name(object_name, details["max_len"])
        if package_name.upper() != "$TMP":
            self._assert_package_allowed(package_name)

        params = self._validation_params(object_type_id, object_name, description, package_name, content)
        try:
            response = await self._request(
                "POST",
                f"/sap/bc/adt/{details['validation_path']}",
                params=params,
                accept="application/vnd.sap.as+xml, application/xml, */*",
            )
        except SapBackendError as error:
            return {"message": "Validation failed", "error": str(error), "details": error.details}

        record = self._parse_asx_data(response.text)
        severity = (record.get("SEVERITY") or "").upper()
        message = record.get("SHORT_TEXT") or "Validation finished"
        result = {"message": message, "severity": severity or "OK", "recordingRequired": package_name.upper() != "$TMP"}
        if severity in {"ERROR", "A", "E", "X"}:
            result["error"] = message
        return result

    async def creation_create_object(
        self,
        destination: str,
        object_type: str,
        object_content: str,
        transport_request_number: str,
    ) -> dict[str, Any]:
        self._assert_destination(destination)
        self._assert_write_allowed("Create object through ADT-compatible creation workflow")
        content = self._object_content(object_content)
        object_type_id = self._creatable_type_id(object_type)
        details = self._creatable_type(object_type)
        object_name = self._required_content(content, "name")
        description = self._required_content(content, "description")
        package_name = self._required_content(content, "packageName", "package", "developmentPackage")
        if package_name.upper() != "$TMP":
            self._assert_package_allowed(package_name)
        self._validate_object_name(object_name, details["max_len"])

        body = self._creation_body(object_type_id, details, content, object_name, description, package_name)
        creation_path = details["creation_path"].format(parent=quote((content.get("parentName") or "").lower()))
        response = await self._request(
            "POST",
            f"/sap/bc/adt/{creation_path}",
            params={"corrNr": transport_request_number or ""},
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/*; charset=utf-8"},
            accept="application/xml, application/*, text/plain, */*",
        )
        return {
            "message": f"{object_type_id} {object_name.upper()} created",
            "filePath": self._created_object_path(object_type_id, object_name, content),
            "status_code": response.status_code,
            "etag": response.headers.get("etag"),
        }

    def _parse_type_structure(self, text: str) -> list[dict[str, str]]:
        root = ET.fromstring(text)
        objects = []
        for element in root.iter():
            if self._xml_local_name(element.tag) != "SEU_ADT_OBJECT_TYPE_DESCRIPTOR":
                continue
            record = self._direct_child_texts(element)
            object_type = record.get("OBJECT_TYPE")
            if object_type:
                objects.append(
                    {
                        "name": record.get("OBJECT_TYPE_LABEL") or CREATABLE_OBJECT_TYPES.get(object_type, {}).get("name", object_type),
                        "objectType": object_type,
                    }
                )
        return objects

    def _validation_params(
        self,
        object_type: str,
        object_name: str,
        description: str,
        package_name: str,
        content: dict[str, Any],
    ) -> dict[str, str]:
        params = {"objtype": object_type, "objname": object_name, "description": description}
        if object_type in {"FUGR/FF", "FUGR/I"}:
            params["fugrname"] = self._required_content(content, "parentName")
        elif object_type == "SRVB/SVB":
            params["serviceBindingVersion"] = content.get("serviceBindingVersion", "ODATA\\V2")
            params["serviceDefinition"] = self._required_content(content, "serviceDefinition", "service")
            params["package"] = package_name
        else:
            params["packagename"] = package_name
        if object_type == "DEVC/K":
            params["swcomp"] = str(content.get("softwareComponent") or content.get("swcomp") or "")
            params["transportLayer"] = str(content.get("transportLayer") or "")
            params["packagetype"] = str(content.get("packageType") or content.get("packagetype") or "development")
        return params

    def _creation_body(
        self,
        object_type: str,
        details: dict[str, Any],
        content: dict[str, Any],
        object_name: str,
        description: str,
        package_name: str,
    ) -> str:
        root = details["root"]
        body = self._creation_body_inner(object_type, content, object_name, package_name)
        responsible = self._xml_escape(str(content.get("responsible") or ""))
        responsible_attr = f'adtcore:responsible="{responsible}"' if responsible else ""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<{root} {details['namespace']} xmlns:adtcore=\"http://www.sap.com/adt/core\" "
            f'adtcore:description="{self._xml_escape(description)}" '
            f'adtcore:name="{self._xml_escape(object_name.upper())}" adtcore:type="{self._xml_escape(object_type)}" '
            f'{responsible_attr} {details.get("extra", "")}>{body}</{root}>'
        )

    def _creation_body_inner(
        self, object_type: str, content: dict[str, Any], object_name: str, package_name: str
    ) -> str:
        if object_type == "FUGR/FF":
            parent_name = self._required_content(content, "parentName")
            parent_uri = f"/sap/bc/adt/functions/groups/{quote(parent_name.lower())}"
            return (
                f'<adtcore:containerRef adtcore:name="{self._xml_escape(parent_name.upper())}" '
                f'adtcore:type="FUGR/F" adtcore:uri="{parent_uri}" />'
            )
        if object_type == "SRVB/SVB":
            service = self._required_content(content, "serviceDefinition", "service")
            binding_type = str(content.get("bindingType") or "ODATA")
            category = str(content.get("bindingCategory") or content.get("category") or "0")
            binding_version = str(content.get("serviceBindingVersion") or "V2").replace("ODATA\\", "")
            return (
                f'<adtcore:packageRef adtcore:name="{self._xml_escape(package_name.upper())}"/>'
                f'<srvb:services srvb:name="{self._xml_escape(object_name.upper())}">'
                '<srvb:content srvb:version="0001">'
                f'<srvb:serviceDefinition adtcore:name="{self._xml_escape(service.upper())}"/>'
                '</srvb:content></srvb:services>'
                f'<srvb:binding srvb:category="{self._xml_escape(category)}" '
                f'srvb:type="{self._xml_escape(binding_type)}" srvb:version="{self._xml_escape(binding_version)}">'
                '<srvb:implementation adtcore:name=""/></srvb:binding>'
            )
        if object_type == "DEVC/K":
            parent = str(content.get("parentName") or package_name)
            package_type = str(content.get("packageType") or content.get("packagetype") or "development")
            return (
                f'<adtcore:packageRef adtcore:name="{self._xml_escape(parent.upper())}"/>'
                f'<pak:attributes pak:packageType="{self._xml_escape(package_type)}"/>'
                f'<pak:superPackage adtcore:name="{self._xml_escape(parent.upper())}"/>'
            )
        return f'<adtcore:packageRef adtcore:name="{self._xml_escape(package_name.upper())}"/>'

    def _created_object_path(self, object_type: str, object_name: str, content: dict[str, Any]) -> str:
        details = self._creatable_type(object_type)
        creation_path = details["creation_path"].format(parent=quote(str(content.get("parentName") or "").lower()))
        return f"/sap/bc/adt/{creation_path}/{quote(object_name.lower())}"
