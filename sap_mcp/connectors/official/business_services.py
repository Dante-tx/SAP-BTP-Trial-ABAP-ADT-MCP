from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

from sap_mcp.connectors.official.base import OfficialBaseMixin
from sap_mcp.errors import ValidationError


class BusinessServicesMixin(OfficialBaseMixin):
    async def business_services_fetch_services(self, destination: str, service_binding_name: str) -> dict[str, Any]:
        self._assert_destination(destination)
        object_name = service_binding_name.upper()
        response = await self._request(
            "GET",
            f"/sap/bc/adt/businessservices/bindings/{quote(object_name.lower())}",
            accept="application/vnd.sap.adt.businessservices.servicebinding.v2+xml, application/xml, */*",
        )
        return self._parse_service_binding(response.text, object_name)

    async def business_services_fetch_service_information(
        self,
        destination: str,
        service_binding_name: str,
        service_name: str,
        service_definition: str,
        service_version: str,
        odata_info_uri: str,
        odata_version: str,
        is_published: bool | None = None,
    ) -> dict[str, Any]:
        self._assert_destination(destination)
        if odata_version.upper() == "V4" and is_published is False:
            raise ValidationError(f"Service binding {service_binding_name} is not published")
        response = await self._request("GET", odata_info_uri, accept="application/xml, application/json, */*")
        return self._parse_odata_service_information(response.text, odata_info_uri, service_name, service_definition, service_version)

    def _parse_service_binding(self, text: str, service_binding_name: str) -> dict[str, Any]:
        root = ET.fromstring(text)
        root_attrs = {self._xml_local_name(key): value for key, value in root.attrib.items()}
        result = {
            "bindingType": "",
            "bindingCategory": "",
            "isPublished": "published=\"true\"" in text or root_attrs.get("bindingCreated", "").lower() == "true",
            "odataVersion": "V4" if "odatav4" in text.lower() or "V4" in text else "V2",
            "odataInfoUri": [],
            "services": [],
        }
        service_map: dict[str, dict[str, Any]] = {}
        current_service = service_binding_name
        for element in root.iter():
            tag = self._xml_local_name(element.tag)
            attrs = {self._xml_local_name(key): value for key, value in element.attrib.items()}
            if tag == "binding":
                result["bindingType"] = attrs.get("type", result["bindingType"])
                result["bindingCategory"] = attrs.get("category", result["bindingCategory"])
                if attrs.get("version"):
                    result["odataVersion"] = attrs["version"].replace("ODATA\\", "").upper()
            elif tag == "services":
                current_service = attrs.get("name") or service_binding_name
                service_map.setdefault(current_service, {"name": current_service, "content": []})
            elif tag == "content":
                target = service_map.setdefault(current_service, {"name": current_service, "content": []})
                target["content"].append(
                    {
                        "serviceDefinition": self._service_definition_name(element),
                        "serviceVersion": attrs.get("version", ""),
                    }
                )
            elif tag == "link":
                href = attrs.get("href", "")
                if href and ("metadata" in href.lower() or "odata" in href.lower()):
                    result["odataInfoUri"].append({"href": href})
        if not result["odataInfoUri"]:
            odata_path = "odatav2" if result["odataVersion"] == "V2" else "odatav4"
            result["odataInfoUri"].append({"href": f"/sap/bc/adt/businessservices/{odata_path}/{quote(service_binding_name.lower())}"})
        result["services"] = list(service_map.values()) or [
            {"name": service_binding_name, "content": [{"serviceDefinition": "", "serviceVersion": "0001"}]}
        ]
        return result

    def _service_definition_name(self, content_element: ET.Element) -> str:
        for child in content_element.iter():
            if self._xml_local_name(child.tag) == "serviceDefinition":
                return {self._xml_local_name(key): value for key, value in child.attrib.items()}.get("name", "")
        return ""

    def _parse_odata_service_information(
        self, text: str, odata_info_uri: str, service_name: str, service_definition: str, service_version: str
    ) -> dict[str, Any]:
        service_url = odata_info_uri
        entity_sets = []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return {"serviceUrl": service_url, "entitySets": entity_sets, "raw": text}
        for element in root.iter():
            tag = self._xml_local_name(element.tag)
            attrs = {self._xml_local_name(key): value for key, value in element.attrib.items()}
            if tag == "link" and attrs.get("href") and ("runtime" in attrs.get("rel", "") or "service" in attrs.get("rel", "")):
                service_url = attrs["href"]
            elif tag == "EntitySet":
                entity_sets.append({"name": attrs.get("Name", ""), "navigations": self._entity_set_navigations(element)})
        return {
            "serviceUrl": service_url,
            "entitySets": entity_sets,
            "serviceName": service_name,
            "serviceDefinition": service_definition,
            "serviceVersion": service_version,
        }

    def _entity_set_navigations(self, entity_set: ET.Element) -> list[str]:
        navigations = []
        for child in entity_set:
            if self._xml_local_name(child.tag) == "NavigationPropertyBinding":
                attrs = {self._xml_local_name(key): value for key, value in child.attrib.items()}
                if attrs.get("Path"):
                    navigations.append(attrs["Path"])
        return navigations
