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
        service_name: str | None = None,
        service_definition: str | None = None,
        service_version: str | None = None,
        odata_info_uri: str | None = None,
        odata_version: str | None = None,
        is_published: bool | None = None,
    ) -> dict[str, Any]:
        self._assert_destination(destination)
        if not all([service_name, service_definition, service_version, odata_info_uri, odata_version]):
            binding = await self.business_services_fetch_services(destination, service_binding_name)
            service = self._first_service(binding, service_binding_name)
            content = self._first_service_content(service)
            service_name = service_name or service.get("name") or service_binding_name
            service_definition = service_definition or content.get("serviceDefinition") or ""
            service_version = service_version or content.get("serviceVersion") or "0001"
            odata_info_uri = odata_info_uri or self._first_odata_info_uri(binding, service_binding_name)
            odata_version = odata_version or binding.get("odataVersion") or "V4"
            if is_published is None:
                is_published = bool(binding.get("isPublished"))
        odata_info_uri = self._service_info_uri_with_service_name(odata_info_uri, service_binding_name)
        if odata_version.upper() == "V4" and is_published is False:
            raise ValidationError(f"Service binding {service_binding_name} is not published")
        response = await self._request("GET", odata_info_uri, accept="application/xml, application/json, */*")
        return self._parse_odata_service_information(response.text, odata_info_uri, service_name, service_definition, service_version)

    def _first_service(self, binding: dict[str, Any], service_binding_name: str) -> dict[str, Any]:
        services = binding.get("services") or []
        if services and isinstance(services[0], dict):
            return services[0]
        return {"name": service_binding_name, "content": [{"serviceDefinition": "", "serviceVersion": "0001"}]}

    def _first_service_content(self, service: dict[str, Any]) -> dict[str, str]:
        content = service.get("content") or []
        if content and isinstance(content[0], dict):
            return content[0]
        return {"serviceDefinition": "", "serviceVersion": "0001"}

    def _first_odata_info_uri(self, binding: dict[str, Any], service_binding_name: str) -> str:
        uris = binding.get("odataInfoUri") or []
        if uris and isinstance(uris[0], dict) and uris[0].get("href"):
            return uris[0]["href"]
        odata_path = "odatav2" if binding.get("odataVersion") == "V2" else "odatav4"
        return f"/sap/bc/adt/businessservices/{odata_path}/{quote(service_binding_name.lower())}"

    def _service_info_uri_with_service_name(self, uri: str, service_binding_name: str) -> str:
        if "?" in uri:
            return uri
        if "/sap/bc/adt/businessservices/odatav" not in uri.lower():
            return uri
        return f"{uri}?servicename={quote(service_binding_name.upper())}"

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
