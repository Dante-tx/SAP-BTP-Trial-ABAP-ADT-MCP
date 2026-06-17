from __future__ import annotations

import fnmatch
import io
import xml.etree.ElementTree as ET
from html import escape
from typing import Any
from urllib.parse import quote

from sap_mcp.auth.browser_sso import BrowserSession
from sap_mcp.config import AbapDevConfig
from sap_mcp.connectors.adt_http import AdtHttpMixin
from sap_mcp.connectors.adt_metadata import AdtMetadataMixin
from sap_mcp.connectors.adt_paths import AdtPathMixin
from sap_mcp.connectors.adt_quality import AdtQualityMixin
from sap_mcp.connectors.official import AdtOfficialCompatibilityMixin
from sap_mcp.connectors.adt_registry import (
    ADT_ACCEPT,
    AdtPathRegistration,
    AdtResponse,
)
from sap_mcp.errors import AuthorizationError, SapBackendError, ValidationError


class AdtConnector(AdtOfficialCompatibilityMixin, AdtHttpMixin, AdtQualityMixin, AdtMetadataMixin, AdtPathMixin):
    def __init__(self, config: AbapDevConfig, session: BrowserSession):
        self.config = config
        self.session = session

    async def discovery(self) -> dict[str, Any]:
        response = await self._request("GET", "/sap/bc/adt/discovery", accept=ADT_ACCEPT)
        self._persist_session_cookies()
        return {
            "connected": True,
            "status_code": response.status_code,
            "content_type": response.content_type,
            "system_url": self.session.system_url,
        }

    async def search_objects(
        self,
        query: str,
        max_results: int = 20,
        object_type: str | None = None,
        package: str | None = None,
    ) -> list[dict[str, Any]]:
        if package:
            self._assert_package_read_allowed(package)
        results = await self._search_repository_objects(query, max_results, object_type, package)
        if results or not package or query.strip() in {"", "*"}:
            return results
        if object_type and not self._is_source_search_type(object_type):
            return results
        if not self._is_package_write_allowed(package):
            return results
        if await self._is_large_super_package(package):
            return results
        return await self._search_source_in_package(query, max_results, object_type, package)

    async def _search_repository_objects(
        self,
        query: str,
        max_results: int = 20,
        object_type: str | None = None,
        package: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {"query": query, "maxResults": str(max(1, min(max_results, 100)))}
        params["operation"] = "quickSearch"
        if object_type:
            params["objectType"] = object_type
        if package:
            params["packageName"] = package
        response = await self._request(
            "GET",
            "/sap/bc/adt/repository/informationsystem/search",
            params=params,
            accept="application/*",
        )
        results = self._parse_search_results(response.text)
        await self._enrich_descriptions(results)
        return results

    async def _search_source_in_package(
        self,
        query: str,
        max_results: int,
        object_type: str | None,
        package: str,
    ) -> list[dict[str, Any]]:
        object_types = [object_type] if object_type else ["CLAS", "INTF", "DDLS", "DCLS", "BDEF", "DDLX", "SRVD", "TABL", "DTEL", "DOMA"]
        source_matches: list[dict[str, Any]] = []
        for source_object_type in object_types:
            objects = await self._search_repository_objects("*", 100, source_object_type, package)
            for item in objects:
                name = item.get("name")
                if not name:
                    continue
                try:
                    source = await self.read_source(source_object_type or item.get("type", "CLAS"), name)
                except Exception:
                    continue
                source_matches.extend(self._source_matches(query, source, item))
                if len(source_matches) >= max_results:
                    return source_matches[:max_results]
        return source_matches[:max_results]

    async def read_source(
        self,
        object_type: str | None = None,
        name: str | None = None,
        scope: str | None = None,
        include_type: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        target = self._resolve_source_target(object_type, name, scope, include_type, uri)
        path = target.uri
        response = await self._request("GET", path, accept="text/plain, application/xml, */*")
        result = {
            "object_type": target.object_type,
            "name": target.name,
            "source": response.text,
            "source_kind": target.source_kind,
            "uri": path,
            "etag": response.headers.get("etag"),
            "content_type": response.content_type,
            "scope": target.scope,
            "include_type": target.include_type,
            "round_trippable": target.round_trippable,
            "writable_uri": path if target.round_trippable else None,
            "writable_etag": response.headers.get("etag") if target.round_trippable else None,
        }
        if target.include_type:
            result["source_part"] = target.include_type
        if target.read_hint:
            result["read_hint"] = target.read_hint
        if self._is_oo_source_type(target.object_type) and target.source_kind == "source_with_includes":
            return await self._with_oo_source_includes(result, target.object_type, target.name, path, response)
        return result

    async def get_object_metadata(
        self,
        object_type: str | None = None,
        name: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        path = self._metadata_path(object_type, name, uri)
        response = await self._request("GET", path, accept="application/xml, application/*, */*")
        requested_type = object_type.upper() if object_type else None
        requested_name = name.upper() if name else None
        return self._parse_object_metadata(
            response.text,
            path,
            response.headers.get("etag"),
            response.content_type,
            response.status_code,
            requested_type,
            requested_name,
        )

    async def create_object(
        self,
        object_type: str,
        name: str,
        package: str,
        description: str,
        reason: str,
        source: str | None = None,
        service_binding_version: str | None = None,
    ) -> dict[str, Any]:
        self._assert_write_allowed(reason)
        self._assert_package_allowed(package)
        registration = self._path_registration(
            object_type,
            "Writable types are class, interface, ddls/cds, dcls/dcl, bdef, ddlx, srvd, srvb, tabl, dtel, doma, devc, prog, fugr, and func",
        )
        initial_source = source if source is not None else self._initial_create_source(registration, name, description)
        if registration.canonical_type in {"PROG", "FUGR"}:
            return await self._create_metadata_object(registration, name, package, description)
        if registration.canonical_type == "FUNC":
            return await self._create_function_module(registration, name, package, description, initial_source)
        if registration.canonical_type == "DTEL":
            return await self._create_data_element(registration, name, package, description)
        if registration.canonical_type == "DOMA":
            return await self._create_domain(registration, name, package, description)
        if registration.canonical_type == "DEVC":
            return await self._create_package(registration, name, package, description)
        if registration.canonical_type == "DDLS":
            return await self._create_ddls(registration, name, package, description, initial_source)
        if registration.canonical_type == "SRVB":
            return await self._create_srvb(
                registration,
                name,
                package,
                description,
                initial_source,
                service_binding_version,
            )
        path = self._source_path(object_type, name)
        response = await self._request(
            "PUT",
            path,
            content=initial_source.encode("utf-8"),
            headers={
                "If-None-Match": "*",
                "Content-Type": "text/plain; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/xml, text/plain, */*",
        )
        return self._created_result(object_type, name, package, response)

    async def _create_package(
        self, registration: AdtPathRegistration, name: str, parent_package: str, description: str
    ) -> dict[str, Any]:
        object_name = name.upper()
        metadata = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package:package xmlns:package="http://www.sap.com/adt/packages" '
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:name="{object_name}" adtcore:type="DEVC/K" '
            f'adtcore:description="{self._xml_escape(description)}">'
            f"{self._package_ref_xml(parent_package)}"
            "</package:package>"
        )
        response = await self._request(
            "POST",
            self._collection_path(registration),
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/vnd.sap.adt.package.v2+xml; charset=utf-8",
                "X-SAP-ADT-Package": parent_package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/vnd.sap.adt.package.v2+xml, application/xml, */*",
        )
        return self._created_result("DEVC", object_name, parent_package, response)

    async def _create_metadata_object(
        self,
        registration: AdtPathRegistration,
        name: str,
        package: str,
        description: str,
    ) -> dict[str, Any]:
        if not registration.create_xml_name or not registration.create_xml_namespace or not registration.create_adt_type:
            raise ValidationError(f"{registration.display_name} does not define metadata creation XML")
        object_name = name.upper()
        metadata = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<{registration.create_xml_name} {registration.create_xml_namespace} "
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:name="{object_name}" adtcore:type="{registration.create_adt_type}" '
            f'adtcore:description="{self._xml_escape(description)}" '
            'adtcore:abapLanguageVersion="cloudDevelopment">'
            f"{self._package_ref_xml(package)}"
            f"</{registration.create_xml_name}>"
        )
        response = await self._request(
            "POST",
            self._collection_path(registration),
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/xml; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/xml, application/*, */*",
        )
        return self._created_result(registration.canonical_type, object_name, package, response)

    async def _create_domain(
        self, registration: AdtPathRegistration, name: str, package: str, description: str
    ) -> dict[str, Any]:
        object_name = name.upper()
        label = self._xml_escape(description)
        metadata = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<blue:wbobj xmlns:blue="http://www.sap.com/wbobj/dictionary/doma" '
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:name="{object_name}" adtcore:type="DOMA/DM" '
            f'adtcore:description="{label}" adtcore:abapLanguageVersion="cloudDevelopment">'
            f"{self._package_ref_xml(package)}"
            '<doma:domain xmlns:doma="http://www.sap.com/adt/dictionary/domains">'
            "<doma:dataType>CHAR</doma:dataType><doma:dataTypeLength>000001</doma:dataTypeLength>"
            "<doma:dataTypeDecimals>000000</doma:dataTypeDecimals>"
            "<doma:outputLength>000001</doma:outputLength><doma:conversionExit/>"
            "</doma:domain></blue:wbobj>"
        )
        response = await self._request(
            "POST",
            self._collection_path(registration),
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/vnd.sap.adt.domains.v2+xml; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/vnd.sap.adt.domains.v2+xml, application/xml, */*",
        )
        return self._created_result("DOMA", object_name, package, response)

    async def _create_function_module(
        self, registration: AdtPathRegistration, name: str, package: str, description: str, function_group: str
    ) -> dict[str, Any]:
        object_name = name.upper()
        group_name = function_group.strip().upper()
        if not group_name:
            raise ValidationError("Function module creation requires source to contain the function group name")
        await self._assert_object_write_allowed("FUGR", group_name)
        metadata = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<fmodule:abapFunctionModule xmlns:fmodule="http://www.sap.com/adt/functions/fmodules" '
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:name="{object_name}" adtcore:type="FUGR/FF" '
            f'adtcore:description="{self._xml_escape(description)}">'
            f'<adtcore:containerRef adtcore:uri="/sap/bc/adt/functions/groups/{quote(group_name.lower())}" '
            f'adtcore:type="FUGR/F" adtcore:name="{group_name}"/>'
            "</fmodule:abapFunctionModule>"
        )
        response = await self._request(
            "POST",
            self._collection_path(registration, name),
            content=metadata.encode("utf-8"),
            headers={"Content-Type": "application/xml; charset=utf-8"},
            accept="application/xml, application/*, */*",
        )
        return self._created_result("FUNC", object_name, package, response, function_group=group_name)

    async def _create_data_element(
        self, registration: AdtPathRegistration, name: str, package: str, description: str
    ) -> dict[str, Any]:
        object_name = name.upper()
        label = self._xml_escape(description)
        metadata = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<blue:wbobj xmlns:blue="http://www.sap.com/wbobj/dictionary/dtel" '
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:name="{object_name}" adtcore:type="DTEL/DE" '
            f'adtcore:description="{label}" adtcore:abapLanguageVersion="cloudDevelopment">'
            f"{self._package_ref_xml(package)}"
            '<dtel:dataElement xmlns:dtel="http://www.sap.com/adt/dictionary/dataelements">'
            "<dtel:typeKind>predefinedAbapType</dtel:typeKind><dtel:typeName/>"
            "<dtel:dataType>CHAR</dtel:dataType><dtel:dataTypeLength>000001</dtel:dataTypeLength>"
            "<dtel:dataTypeDecimals>000000</dtel:dataTypeDecimals>"
            f"<dtel:shortFieldLabel>{label}</dtel:shortFieldLabel><dtel:shortFieldLength>10</dtel:shortFieldLength><dtel:shortFieldMaxLength>10</dtel:shortFieldMaxLength>"
            f"<dtel:mediumFieldLabel>{label}</dtel:mediumFieldLabel><dtel:mediumFieldLength>20</dtel:mediumFieldLength><dtel:mediumFieldMaxLength>20</dtel:mediumFieldMaxLength>"
            f"<dtel:longFieldLabel>{label}</dtel:longFieldLabel><dtel:longFieldLength>40</dtel:longFieldLength><dtel:longFieldMaxLength>40</dtel:longFieldMaxLength>"
            f"<dtel:headingFieldLabel>{label}</dtel:headingFieldLabel><dtel:headingFieldLength>55</dtel:headingFieldLength><dtel:headingFieldMaxLength>55</dtel:headingFieldMaxLength>"
            "<dtel:searchHelp/><dtel:searchHelpParameter/><dtel:setGetParameter/><dtel:defaultComponentName/>"
            "<dtel:deactivateInputHistory>false</dtel:deactivateInputHistory><dtel:changeDocument>false</dtel:changeDocument>"
            "<dtel:leftToRightDirection>false</dtel:leftToRightDirection><dtel:deactivateBIDIFiltering>false</dtel:deactivateBIDIFiltering>"
            "</dtel:dataElement></blue:wbobj>"
        )
        response = await self._request(
            "POST",
            self._collection_path(registration),
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/vnd.sap.adt.dataelements.v2+xml; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/vnd.sap.adt.dataelements.v2+xml, application/xml, */*",
        )
        return self._created_result("DTEL", object_name, package, response)

    async def _create_ddls(
        self, registration: AdtPathRegistration, name: str, package: str, description: str, source: str
    ) -> dict[str, Any]:
        object_name = name.upper()
        metadata = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ddl:ddlSource xmlns:ddl="http://www.sap.com/adt/ddic/ddlsources" '
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            'xmlns:abapsource="http://www.sap.com/adt/abapsource" '
            f'adtcore:name="{object_name}" adtcore:type="DDLS/DF" '
            f'adtcore:description="{self._xml_escape(description)}" '
            'adtcore:abapLanguageVersion="cloudDevelopment" '
            'ddl:source_origin="0" ddl:source_type="view entity" '
            'abapsource:sourceUri="source/main">'
            f"{self._package_ref_xml(package)}"
            "</ddl:ddlSource>"
        )
        create_response = await self._request(
            "POST",
            self._collection_path(registration),
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/vnd.sap.adt.ddlSource+xml; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/vnd.sap.adt.ddlSource+xml, application/xml, */*",
        )
        source_response = await self._request(
            "PUT",
            self._source_path(registration.canonical_type, name),
            content=source.encode("utf-8"),
            headers={
                "If-Match": create_response.headers.get("etag", "*"),
                "Content-Type": "text/plain; charset=utf-8",
            },
            accept="application/xml, text/plain, */*",
        )
        return self._created_result("DDLS", object_name, package, source_response)

    async def _create_srvb(
        self,
        registration: AdtPathRegistration,
        name: str,
        package: str,
        description: str,
        service_definition: str,
        service_binding_version: str | None = None,
    ) -> dict[str, Any]:
        object_name = name.upper()
        service_definition_name = (service_definition or name).strip().upper()
        odata_version = self._normalize_odata_version(service_binding_version, default="V4")
        metadata = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<srvb:serviceBinding xmlns:srvb="http://www.sap.com/adt/ddic/ServiceBindings" '
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            'srvb:bindingCreated="false" '
            f'adtcore:name="{object_name}" adtcore:type="SRVB/SVB" '
            f'adtcore:description="{self._xml_escape(description)}" '
            'adtcore:abapLanguageVersion="cloudDevelopment">'
            f"{self._package_ref_xml(package)}"
            f'<srvb:services srvb:name="{object_name}">'
            '<srvb:content srvb:version="0001" srvb:minorVersion="0" srvb:patchVersion="0" '
            'srvb:buildVersion="" srvb:releaseState="NOT_RELEASED">'
            f'<srvb:serviceDefinition adtcore:uri="/sap/bc/adt/ddic/srvd/sources/{quote(service_definition_name.lower())}" '
            f'adtcore:type="SRVD/SRV" adtcore:name="{service_definition_name}"/>'
            '<srvb:bindingTypeData><adtcore:content adtcore:encoding="base64"/></srvb:bindingTypeData>'
            '</srvb:content></srvb:services>'
            f'<srvb:binding srvb:type="ODATA" srvb:version="{odata_version}" srvb:category="0">'
            f'<srvb:implementation adtcore:name="{object_name}"/>'
            '</srvb:binding></srvb:serviceBinding>'
        )
        response = await self._request(
            "POST",
            self._collection_path(registration),
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/vnd.sap.adt.businessservices.servicebinding.v2+xml; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/vnd.sap.adt.businessservices.servicebinding.v2+xml, application/xml, */*",
        )
        return self._created_result(
            "SRVB",
            object_name,
            package,
            response,
            service_definition=service_definition_name,
            odata_version=odata_version,
        )

    async def update_source(
        self,
        object_type: str | None,
        name: str | None,
        source: str,
        etag: str,
        reason: str,
        include_type: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        self._assert_write_allowed(reason)
        requested_scope = "include" if include_type else None
        target = self._resolve_source_target(object_type, name, requested_scope, include_type, uri, for_write=True)
        if not target.round_trippable:
            raise ValidationError(
                "This source target is read-only or not directly writable through abap_update_source. "
                f"{target.read_hint or ''}".strip()
            )
        if '"$ADT include:' in source:
            raise ValidationError(
                "Composite source_with_includes output is not round-trippable. Read the exact main/include part first "
                f"and write back using its writable_uri/writable_etag. {target.read_hint or ''}".strip()
            )
        await self._assert_object_write_allowed(target.object_type, target.name)
        path = target.uri
        content_type = "application/xml; charset=utf-8" if self._is_metadata_write_path(path) else "text/plain; charset=utf-8"
        try:
            response = await self._request(
                "PUT",
                path,
                content=source.encode("utf-8"),
                headers={"If-Match": etag, "Content-Type": content_type},
                accept="application/xml, text/plain, */*",
            )
        except SapBackendError as error:
            raise self._augment_update_error(error, target) from error
        return {
            "updated": True,
            "object_type": target.object_type,
            "name": target.name,
            "uri": path,
            "include_type": target.include_type,
            "status_code": response.status_code,
            "etag": response.headers.get("etag"),
            "writable_uri": path,
            "writable_etag": response.headers.get("etag"),
        }

    async def activate_object(self, object_type: str, name: str, reason: str) -> dict[str, Any]:
        result = await self.activate_objects([{"type": object_type, "name": name}], reason)
        # Extract per-object result for the requested object from parsed activation response
        activated = result.get("activated", True)
        obj_results = result.get("object_results", [])
        my_result = obj_results[0] if obj_results else {}
        return {
            "activated": activated,
            "object_type": object_type,
            "name": name.upper(),
            "status_code": result["status_code"],
            "activation_state": my_result.get("state"),
            "activation_state_text": my_result.get("state_text"),
            "messages": my_result.get("messages", []),
        }

    async def activate_objects(self, objects: list[dict[str, str]], reason: str) -> dict[str, Any]:
        if not self.config.allow_activate:
            raise AuthorizationError("ABAP activation is disabled by configuration")
        if not reason.strip():
            raise ValidationError("Activation reason is required")

        references = []
        for item in objects or []:
            object_type = (item.get("type") or item.get("object_type") or "").strip()
            name = (item.get("name") or "").strip()
            if not object_type or not name:
                raise ValidationError("Each object must contain name and type/object_type")
            uri = self._object_path(object_type, name)
            await self._assert_object_write_allowed(object_type, name)
            references.append({"object_type": object_type.upper(), "name": name.upper(), "uri": uri})

        if not references:
            raise ValidationError("At least one object is required")

        object_reference_xml = "".join(
            f'<adtcore:objectReference adtcore:uri="{self._xml_escape(reference["uri"])}" />'
            for reference in references
        )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">'
            f"{object_reference_xml}"
            "</adtcore:objectReferences>"
        )
        response = await self._request(
            "POST",
            "/sap/bc/adt/activation",
            params={"method": "activate"},
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
        )
        # Parse activation response XML to check actual backend results
        object_results, all_activated = self._parse_activation_result(response.text, references)
        return {
            "activated": all_activated,
            "count": len(references),
            "objects": references,
            "object_results": object_results,
            "messages": [message for result in object_results for message in result["messages"]],
            "status_code": response.status_code,
        }

    def _parse_activation_result(
        self, xml_text: str, references: list[dict[str, str]]
    ) -> tuple[list[dict[str, Any]], bool]:
        try:
            root = ET.fromstring(xml_text)
        except (ET.ParseError, TypeError):
            return self._activation_fallback_results(references, "Could not parse activation result")

        messages = [
            self._activation_message(element)
            for element in root.iter()
            if self._xml_local_name(element.tag) in {"msg", "message"}
        ]
        messages = [message for message in messages if message]
        error_types = {"A", "E", "X", "ERROR"}
        has_errors = any(
            (message.get("type") or message.get("severity") or "").upper() in error_types
            for message in messages
        )
        has_failed_state = any(
            (element.attrib.get("state") or self._activation_attr(element, "state")).upper() in error_types
            for element in root.iter()
        )
        activation_executed = not any(
            self._xml_local_name(element.tag) == "properties"
            and (element.attrib.get("activationExecuted") or "").lower() == "false"
            for element in root.iter()
        )
        all_activated = activation_executed and not has_errors and not has_failed_state
        state = "S" if all_activated else "E"
        state_text = "Activated" if all_activated else "Activation failed"

        object_results = []
        for ref in references:
            related_messages = [
                message for message in messages
                if len(references) == 1
                or ref["uri"] in (message.get("href") or "")
                or ref["name"] in (message.get("objDescr") or "").upper()
            ]
            object_results.append({
                "object_type": ref["object_type"],
                "name": ref["name"],
                "state": state,
                "state_text": state_text,
                "activated": all_activated and not any(
                    (message.get("type") or "").upper() in error_types for message in related_messages
                ),
                "messages": related_messages,
            })

        return object_results, all(result["activated"] for result in object_results)

    def _activation_fallback_results(
        self, references: list[dict[str, str]], state_text: str
    ) -> tuple[list[dict[str, Any]], bool]:
        return [
            {
                "object_type": ref["object_type"],
                "name": ref["name"],
                "state": "UNKNOWN",
                "state_text": state_text,
                "activated": False,
                "messages": [],
            }
            for ref in references
        ], False

    def _activation_message(self, element: ET.Element) -> dict[str, str]:
        message = {self._xml_local_name(key): value for key, value in element.attrib.items()}
        text_parts = []
        if element.text and element.text.strip():
            text_parts.append(element.text.strip())
        for child in element.iter():
            if child is not element and child.text and child.text.strip():
                text_parts.append(child.text.strip())
        if text_parts:
            message["text"] = " ".join(text_parts)
        return message

    def _activation_attr(self, element: ET.Element, name: str) -> str:
        return next((value for key, value in element.attrib.items() if self._xml_local_name(key) == name), "")

    def _xml_local_name(self, name: str) -> str:
        return name.rsplit("}", 1)[-1].split(":", 1)[-1]

    async def delete_object(self, object_type: str, name: str, reason: str) -> dict[str, Any]:
        self._assert_write_allowed(reason)
        await self._assert_object_write_allowed(object_type, name)
        uri = self._object_path(object_type, name)
        metadata = await self._request("GET", uri, accept="application/xml, application/*, */*")
        etag = metadata.headers.get("etag", "*")
        try:
            response = await self._request(
                "DELETE",
                uri,
                headers={"If-Match": etag},
                accept="application/xml, text/plain, */*",
            )
        except SapBackendError as error:
            server_etag = self._server_etag_from_precondition(str(error))
            if not server_etag:
                raise
            response = await self._request(
                "DELETE",
                uri,
                headers={"If-Match": server_etag},
                accept="application/xml, text/plain, */*",
            )
        return {"deleted": True, "object_type": object_type, "name": name.upper(), "status_code": response.status_code}

    async def publish_service_binding(
        self, name: str, reason: str, odata_version: str | None = None
    ) -> dict[str, Any]:
        self._assert_write_allowed(reason)
        if not reason.strip():
            raise ValidationError("Publish reason is required")
        await self._assert_object_write_allowed("SRVB", name)
        object_name = name.upper()
        metadata = await self.read_source("SRVB", object_name)
        detected_version = self._service_binding_odata_version(metadata["source"], default=None)
        version = self._normalize_odata_version(odata_version or detected_version, default="V4")
        if odata_version and detected_version and version != detected_version:
            raise ValidationError(
                f"Service binding {object_name} is {detected_version}; requested publish version was {version}"
            )
        odata_path = f"odata{version.lower()}"
        if self._service_binding_published(metadata["source"]):
            return {
                "published": True,
                "changed": False,
                "object_type": "SRVB",
                "name": object_name,
                "odata_version": version,
                "status_code": metadata.get("status_code", 200),
            }

        uri = f"/sap/bc/adt/businessservices/{odata_path}/{quote(object_name)}?servicename={quote(object_name)}"
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">'
            f'<adtcore:objectReference adtcore:uri="{self._xml_escape(uri)}" '
            'adtcore:type="SRVB/SVB" '
            f'adtcore:name="{object_name}" />'
            "</adtcore:objectReferences>"
        )
        response = await self._request(
            "POST",
            f"/sap/bc/adt/businessservices/{odata_path}/publishjobs",
            params={"servicename": object_name},
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/xml; charset=utf-8"},
            accept="application/xml, application/*, */*",
        )
        status = self._parse_status_messages(response.text)
        has_error = any(message.get("severity", "").upper() == "ERROR" for message in status)
        if has_error:
            messages = "; ".join(message.get("text", "") for message in status if message.get("text"))
            raise SapBackendError(f"Service binding publish failed: {messages or response.text[:500]}")
        return {
            "published": True,
            "changed": True,
            "object_type": "SRVB",
            "name": object_name,
            "odata_version": version,
            "status_code": response.status_code,
            "messages": status,
        }

    def _normalize_odata_version(self, version: str | None, default: str | None = "V4") -> str:
        raw_value = version or default
        if not raw_value:
            raise ValidationError("OData version must be V2 or V4")
        raw = raw_value.strip().upper()
        raw = raw.replace("ODATA", "").replace("\\", "").replace("/", "").strip()
        if raw in {"2", "V2"}:
            return "V2"
        if raw in {"4", "V4"}:
            return "V4"
        raise ValidationError("OData version must be V2 or V4")

    def _service_binding_odata_version(self, text: str, default: str | None = "V4") -> str | None:
        try:
            root = ET.fromstring(text)
        except (ET.ParseError, TypeError):
            lower_text = (text or "").lower()
            if "odatav2" in lower_text or "odata\\v2" in lower_text or 'version="v2"' in lower_text:
                return "V2"
            if "odatav4" in lower_text or "odata\\v4" in lower_text or 'version="v4"' in lower_text:
                return "V4"
            return self._normalize_odata_version(default) if default else None
        for element in root.iter():
            if self._xml_local_name(element.tag) == "binding":
                attrs = {self._xml_local_name(key): value for key, value in element.attrib.items()}
                if attrs.get("version"):
                    return self._normalize_odata_version(attrs["version"], default=default)
        return self._normalize_odata_version(default) if default else None

    def _service_binding_published(self, text: str) -> bool:
        try:
            root = ET.fromstring(text)
        except (ET.ParseError, TypeError):
            lower_text = (text or "").lower()
            return 'published="true"' in lower_text or "published='true'" in lower_text
        for element in root.iter():
            attrs = {self._xml_local_name(key): value for key, value in element.attrib.items()}
            if attrs.get("published", "").lower() == "true" or attrs.get("bindingCreated", "").lower() == "true":
                return True
        return False











































    async def _is_large_super_package(self, package: str) -> bool:
        try:
            metadata = await self._request(
                "GET",
                f"/sap/bc/adt/packages/{quote(package.lower())}",
                accept="application/vnd.sap.adt.packages.v2+xml, application/xml, */*",
            )
        except Exception:
            return False
        subpackages = 0
        inside_subpackages = False
        for event, elem in ET.iterparse(io.StringIO(metadata.text), events=("start", "end")):
            tag = elem.tag.rsplit("}", 1)[-1]
            if event == "start" and tag == "subPackages":
                inside_subpackages = True
            elif event == "end" and tag == "subPackages":
                inside_subpackages = False
            elif event == "start" and inside_subpackages and tag == "packageRef":
                subpackages += 1
                if subpackages > 20:
                    return True
        return False


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
        except Exception:
            return result

        parts = [
            {
                "include_type": "main",
                "uri": main_path,
                "source": main_response.text,
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
            except Exception:
                continue
            parts.append(
                {
                    **include,
                    "source": include_response.text,
                    "etag": include_response.headers.get("etag", include.get("etag")),
                    "content_type": include_response.content_type,
                    "scope": "include",
                    "source_kind": "source",
                    "round_trippable": True,
                    "writable_uri": include["uri"],
                    "writable_etag": include_response.headers.get("etag", include.get("etag")),
                }
            )

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
            for part in parts
            if part["include_type"] != "main"
        ]
        result["source"] = "\n\n".join(self._format_source_part(part) for part in parts if part.get("source", "").strip())
        return result

    async def _oo_source_includes(self, object_type: str, name: str) -> list[dict[str, Any]]:
        normalized_type = object_type.lower().split("/", 1)[0]
        collection = "interfaces" if normalized_type in {"interface", "intf"} else "classes"
        object_path = f"/sap/bc/adt/oo/{collection}/{quote(name.lower())}"
        base_path = f"{object_path}/"
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
                includes.append(
                    {
                        "include_type": include_type,
                        "uri": self._adt_relative_url(base_path, href),
                        "etag": link.attrib.get("etag"),
                    }
                )
        order = {"main": 0, "definitions": 1, "implementations": 2, "macros": 3, "testclasses": 4}
        return sorted(includes, key=lambda item: order.get(item["include_type"], 99))


    def _format_source_part(self, part: dict[str, Any]) -> str:
        include_type = part["include_type"]
        source = part.get("source", "")
        if include_type == "main":
            return source
        return f'"$ADT include: {include_type} ({part["uri"]})\n{source}'

    def _source_matches(self, query: str, source_result: dict[str, Any], repository_item: dict[str, Any]) -> list[dict[str, Any]]:
        needle = query.casefold()
        if not needle:
            return []
        parts = source_result.get("source_parts") or [
            {
                "include_type": source_result.get("source_part", "main"),
                "uri": source_result.get("uri"),
                "source": source_result.get("source", ""),
            }
        ]
        matches: list[dict[str, Any]] = []
        for part in parts:
            source = part.get("source", "")
            for line_number, line in enumerate(source.splitlines(), start=1):
                if needle not in line.casefold():
                    continue
                parent_name = repository_item.get("name", source_result.get("name", ""))
                include_type = part.get("include_type", "main")
                uri = part.get("uri", source_result.get("uri", ""))
                matches.append(
                    {
                        "uri": f"{uri}#line={line_number}",
                        "type": "SOURCE/LOCAL",
                        "name": f"{parent_name}:{include_type}:{line_number}",
                        "packageName": repository_item.get("packageName"),
                        "description": f"Source match in {parent_name} {include_type} line {line_number}",
                        "parentUri": repository_item.get("uri"),
                        "parentType": repository_item.get("type"),
                        "parentName": parent_name,
                        "includeType": include_type,
                        "line": line_number,
                        "match": line.strip(),
                    }
                )
        return matches








    def _default_source(self, object_type: str, name: str, description: str) -> str:
        normalized_type = object_type.lower()
        object_name = name.upper()
        if normalized_type in {"class", "clas"}:
            return (
                f'CLASS {object_name} DEFINITION PUBLIC FINAL CREATE PUBLIC.\n'
                "  PUBLIC SECTION.\n"
                "  PROTECTED SECTION.\n"
                "  PRIVATE SECTION.\n"
                "ENDCLASS.\n\n"
                f"CLASS {object_name} IMPLEMENTATION.\n"
                "ENDCLASS.\n"
            )
        if normalized_type in {"interface", "intf"}:
            return f"INTERFACE {object_name} PUBLIC.\nENDINTERFACE.\n"
        if normalized_type in {"ddls", "cds"}:
            return (
                "@AccessControl.authorizationCheck: #NOT_REQUIRED\n"
                f"@EndUserText.label: '{description}'\n"
                f"define view entity {object_name}\n"
                "  as select from some_table\n"
                "{\n"
                "  key some_key\n"
                "}\n"
            )
        if normalized_type in {"dcls", "dcl"}:
            return f"@EndUserText.label: '{description}'\ndefine role {object_name} {{\n}}\n"
        if normalized_type in {"bdef", "behavior", "behavior_definition"}:
            return f"managed implementation in class zbp_{object_name.lower()} unique;\n\ndefine behavior for {object_name}\n{{\n}}\n"
        if normalized_type in {"ddlx", "metadata_extension"}:
            return f"@Metadata.layer: #CORE\nannotate entity {object_name} with\n{{\n}}\n"
        if normalized_type in {"srvd", "service_definition"}:
            return f"@EndUserText.label: '{description}'\ndefine service {object_name} {{\n}}\n"
        if normalized_type in {"srvb", "service_binding"}:
            return object_name
        if normalized_type in {"prog", "program", "prog/p", "report"}:
            return f"REPORT {object_name.lower()}.\n"
        if normalized_type in {"func", "function_module", "fugr/ff"}:
            return ""
        if normalized_type in {"tabl", "table"}:
            return (
                f"@EndUserText.label : '{description}'\n"
                f"define table {object_name} {{\n"
                "  key client : abap.clnt not null;\n"
                "  key id     : abap.char(1) not null;\n"
                "}\n"
            )
        if normalized_type in {"dtel", "data_element", "doma", "domain", "devc", "package"}:
            return ""
        raise ValidationError(
            "Writable types are class, interface, ddls/cds, dcls/dcl, bdef, ddlx, srvd, srvb, tabl, dtel, doma, devc, prog, fugr, and func"
        )

    def _assert_write_allowed(self, reason: str) -> None:
        if not self.config.allow_write:
            raise AuthorizationError("ABAP write access is disabled by configuration")
        if not reason.strip():
            raise ValidationError("Write reason is required")

    def _assert_package_allowed(self, package: str) -> None:
        if not self._is_package_write_allowed(package):
            raise AuthorizationError(f"Package {package} is not in the configured write allowlist")

    def _is_package_write_allowed(self, package: str) -> bool:
        package_upper = package.upper()
        return any(fnmatch.fnmatchcase(package_upper, pattern.upper()) for pattern in self.config.allowed_packages)

    def _assert_package_read_allowed(self, package: str) -> None:
        package_upper = package.upper()
        if not any(fnmatch.fnmatchcase(package_upper, pattern.upper()) for pattern in self.config.readable_packages):
            raise AuthorizationError(f"Package {package} is not in the configured read allowlist")

    async def _assert_object_write_allowed(self, object_type: str, name: str) -> None:
        package = await self._object_package(object_type, name)
        if not package:
            raise AuthorizationError(f"Cannot determine package for {object_type} {name}; write operation blocked")
        self._assert_package_allowed(package)

    async def _object_package(self, object_type: str, name: str) -> str | None:
        registration = self._find_path_registration(object_type)
        search_name = name
        if registration and registration.canonical_type == "FUNC":
            search_name, _ = self._function_module_parts(name)
        search_type = registration.search_type if registration else object_type.upper().split("/", 1)[0]
        try:
            results = await self._search_repository_objects(search_name, 20, search_type, None)
        except Exception:
            return None
        object_name = search_name.upper()
        for item in results:
            if item.get("name", "").upper() == object_name and item.get("packageName"):
                return item["packageName"]
        return None


    def _parse_search_results(self, text: str) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return [{"raw": text}]
        results = []
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag not in {"objectReference", "entry"}:
                continue
            item = {self._clean_xml_name(key): value for key, value in element.attrib.items()}
            title = element.find("{http://www.w3.org/2005/Atom}title")
            if title is not None and title.text:
                item["title"] = title.text
            if item:
                results.append(item)
        return results

    async def _enrich_descriptions(self, results: list[dict[str, Any]]) -> None:
        for item in results:
            if item.get("description"):
                continue
            object_type = item.get("type", "")
            uri = item.get("uri")
            if not uri or not object_type.startswith("CLAS/"):
                continue
            try:
                response = await self._request(
                    "GET",
                    uri,
                    accept="application/vnd.sap.adt.oo.classes.v4+xml, application/xml, */*",
                )
                root = ET.fromstring(response.text)
            except Exception:
                continue
            description = root.attrib.get("{http://www.sap.com/adt/core}description")
            if description:
                item["description"] = description

    def _clean_xml_name(self, name: str) -> str:
        return name.rsplit("}", 1)[-1] if "}" in name else name.split(":", 1)[-1]

    def _xml_escape(self, value: str) -> str:
        return escape(value, quote=True)

    def _package_ref_xml(self, package: str) -> str:
        package_name = package.upper()
        package_uri = quote(package.lower())
        return (
            f'<adtcore:packageRef adtcore:uri="/sap/bc/adt/packages/{package_uri}" '
            f'adtcore:type="DEVC/K" adtcore:name="{package_name}"/>'
        )

    def _created_result(
        self,
        object_type: str,
        name: str,
        package: str,
        response: AdtResponse,
        **extra: Any,
    ) -> dict[str, Any]:
        return {
            "created": True,
            "object_type": object_type,
            "name": name.upper(),
            **extra,
            "package": package.upper(),
            "status_code": response.status_code,
            "etag": response.headers.get("etag"),
        }
