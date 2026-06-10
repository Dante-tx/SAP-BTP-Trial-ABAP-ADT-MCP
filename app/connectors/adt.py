from __future__ import annotations

import fnmatch
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import escape
from typing import Any
from urllib.parse import quote, urljoin

import httpx

from app.auth.browser_sso import BrowserSession
from app.config import AbapDevConfig
from app.errors import AuthorizationError, ConfigError, SapBackendError, ValidationError


ADT_ACCEPT = "application/atom+xml, application/xml, text/plain, */*"


@dataclass(frozen=True)
class AdtResponse:
    status_code: int
    text: str
    headers: dict[str, str]
    content_type: str


class AdtConnector:
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

    async def read_source(self, object_type: str, name: str) -> dict[str, Any]:
        path, source_kind = self._read_path(object_type, name)
        response = await self._request("GET", path, accept="text/plain, application/xml, */*")
        result = {
            "object_type": object_type,
            "name": name.upper(),
            "source": response.text,
            "source_kind": source_kind,
            "uri": path,
            "etag": response.headers.get("etag"),
            "content_type": response.content_type,
        }
        if self._is_oo_source_type(object_type) and source_kind == "source":
            return await self._with_oo_source_includes(result, object_type, name, path, response)
        return result

    async def create_object(
        self,
        object_type: str,
        name: str,
        package: str,
        description: str,
        reason: str,
        source: str | None = None,
    ) -> dict[str, Any]:
        self._assert_write_allowed(reason)
        self._assert_package_allowed(package)
        initial_source = source or self._default_source(object_type, name, description)
        if object_type.lower() in {"prog", "program", "prog/p", "report"}:
            return await self._create_metadata_object(
                "PROG",
                name,
                package,
                description,
                "/sap/bc/adt/programs/programs",
                "program:abapProgram",
                'xmlns:program="http://www.sap.com/adt/programs/programs"',
                "PROG/P",
            )
        if object_type.lower() in {"fugr", "function_group", "fugr/f"}:
            return await self._create_metadata_object(
                "FUGR",
                name,
                package,
                description,
                "/sap/bc/adt/functions/groups",
                "group:abapFunctionGroup",
                'xmlns:group="http://www.sap.com/adt/functions/groups"',
                "FUGR/F",
            )
        if object_type.lower() in {"func", "function_module", "fugr/ff"}:
            return await self._create_function_module(name, package, description, initial_source)
        if object_type.lower() in {"dtel", "data_element"}:
            return await self._create_data_element(name, package, description)
        if object_type.lower() in {"doma", "domain"}:
            return await self._create_domain(name, package, description)
        if object_type.lower() in {"devc", "package"}:
            return await self._create_package(name, package, description)
        if object_type.lower() in {"ddls", "cds"}:
            return await self._create_ddls(name, package, description, initial_source)
        if object_type.lower() in {"srvb", "service_binding"}:
            return await self._create_srvb(name, package, description, initial_source)
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
        return {
            "created": True,
            "object_type": object_type,
            "name": name.upper(),
            "package": package.upper(),
            "status_code": response.status_code,
            "etag": response.headers.get("etag"),
        }

    async def _create_package(self, name: str, parent_package: str, description: str) -> dict[str, Any]:
        object_name = name.upper()
        metadata = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package:package xmlns:package="http://www.sap.com/adt/packages" '
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:name="{object_name}" adtcore:type="DEVC/K" '
            f'adtcore:description="{self._xml_escape(description)}">'
            f'<adtcore:packageRef adtcore:uri="/sap/bc/adt/packages/{quote(parent_package.lower())}" '
            f'adtcore:type="DEVC/K" adtcore:name="{parent_package.upper()}"/>'
            "</package:package>"
        )
        response = await self._request(
            "POST",
            "/sap/bc/adt/packages",
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/vnd.sap.adt.package.v2+xml; charset=utf-8",
                "X-SAP-ADT-Package": parent_package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/vnd.sap.adt.package.v2+xml, application/xml, */*",
        )
        return {
            "created": True,
            "object_type": "DEVC",
            "name": object_name,
            "package": parent_package.upper(),
            "status_code": response.status_code,
            "etag": response.headers.get("etag"),
        }

    async def _create_metadata_object(
        self,
        object_type: str,
        name: str,
        package: str,
        description: str,
        collection_path: str,
        xml_name: str,
        xml_namespace: str,
        adt_type: str,
    ) -> dict[str, Any]:
        object_name = name.upper()
        metadata = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<{xml_name} {xml_namespace} "
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:name="{object_name}" adtcore:type="{adt_type}" '
            f'adtcore:description="{self._xml_escape(description)}" '
            'adtcore:abapLanguageVersion="cloudDevelopment">'
            f'<adtcore:packageRef adtcore:uri="/sap/bc/adt/packages/{quote(package.lower())}" '
            f'adtcore:type="DEVC/K" adtcore:name="{package.upper()}"/>'
            f"</{xml_name}>"
        )
        response = await self._request(
            "POST",
            collection_path,
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/xml; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/xml, application/*, */*",
        )
        return {
            "created": True,
            "object_type": object_type,
            "name": object_name,
            "package": package.upper(),
            "status_code": response.status_code,
            "etag": response.headers.get("etag"),
        }

    async def _create_domain(self, name: str, package: str, description: str) -> dict[str, Any]:
        object_name = name.upper()
        label = self._xml_escape(description)
        metadata = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<blue:wbobj xmlns:blue="http://www.sap.com/wbobj/dictionary/doma" '
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:name="{object_name}" adtcore:type="DOMA/DM" '
            f'adtcore:description="{label}" adtcore:abapLanguageVersion="cloudDevelopment">'
            f'<adtcore:packageRef adtcore:uri="/sap/bc/adt/packages/{quote(package.lower())}" '
            f'adtcore:type="DEVC/K" adtcore:name="{package.upper()}"/>'
            '<doma:domain xmlns:doma="http://www.sap.com/adt/dictionary/domains">'
            "<doma:dataType>CHAR</doma:dataType><doma:dataTypeLength>000001</doma:dataTypeLength>"
            "<doma:dataTypeDecimals>000000</doma:dataTypeDecimals>"
            "<doma:outputLength>000001</doma:outputLength><doma:conversionExit/>"
            "</doma:domain></blue:wbobj>"
        )
        response = await self._request(
            "POST",
            "/sap/bc/adt/ddic/domains",
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/vnd.sap.adt.domains.v2+xml; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/vnd.sap.adt.domains.v2+xml, application/xml, */*",
        )
        return {
            "created": True,
            "object_type": "DOMA",
            "name": object_name,
            "package": package.upper(),
            "status_code": response.status_code,
            "etag": response.headers.get("etag"),
        }

    async def _create_function_module(
        self, name: str, package: str, description: str, function_group: str
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
            f"/sap/bc/adt/functions/groups/{quote(group_name.lower())}/fmodules",
            content=metadata.encode("utf-8"),
            headers={"Content-Type": "application/xml; charset=utf-8"},
            accept="application/xml, application/*, */*",
        )
        return {
            "created": True,
            "object_type": "FUNC",
            "name": object_name,
            "function_group": group_name,
            "package": package.upper(),
            "status_code": response.status_code,
            "etag": response.headers.get("etag"),
        }

    async def _create_data_element(self, name: str, package: str, description: str) -> dict[str, Any]:
        object_name = name.upper()
        label = self._xml_escape(description)
        metadata = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<blue:wbobj xmlns:blue="http://www.sap.com/wbobj/dictionary/dtel" '
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:name="{object_name}" adtcore:type="DTEL/DE" '
            f'adtcore:description="{label}" adtcore:abapLanguageVersion="cloudDevelopment">'
            f'<adtcore:packageRef adtcore:uri="/sap/bc/adt/packages/{quote(package.lower())}" '
            f'adtcore:type="DEVC/K" adtcore:name="{package.upper()}"/>'
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
            "/sap/bc/adt/ddic/dataelements",
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/vnd.sap.adt.dataelements.v2+xml; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/vnd.sap.adt.dataelements.v2+xml, application/xml, */*",
        )
        return {
            "created": True,
            "object_type": "DTEL",
            "name": object_name,
            "package": package.upper(),
            "status_code": response.status_code,
            "etag": response.headers.get("etag"),
        }

    async def _create_ddls(self, name: str, package: str, description: str, source: str) -> dict[str, Any]:
        object_name = name.upper()
        normalized_name = quote(name.lower())
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
            f'<adtcore:packageRef adtcore:uri="/sap/bc/adt/packages/{quote(package.lower())}" '
            f'adtcore:type="DEVC/K" adtcore:name="{package.upper()}"/>'
            "</ddl:ddlSource>"
        )
        create_response = await self._request(
            "POST",
            "/sap/bc/adt/ddic/ddl/sources",
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
            f"/sap/bc/adt/ddic/ddl/sources/{normalized_name}/source/main",
            content=source.encode("utf-8"),
            headers={
                "If-Match": create_response.headers.get("etag", "*"),
                "Content-Type": "text/plain; charset=utf-8",
            },
            accept="application/xml, text/plain, */*",
        )
        return {
            "created": True,
            "object_type": "DDLS",
            "name": object_name,
            "package": package.upper(),
            "status_code": source_response.status_code,
            "etag": source_response.headers.get("etag"),
        }

    async def _create_srvb(self, name: str, package: str, description: str, service_definition: str) -> dict[str, Any]:
        object_name = name.upper()
        service_definition_name = (service_definition or name).strip().upper()
        metadata = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<srvb:serviceBinding xmlns:srvb="http://www.sap.com/adt/ddic/ServiceBindings" '
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            'srvb:bindingCreated="false" '
            f'adtcore:name="{object_name}" adtcore:type="SRVB/SVB" '
            f'adtcore:description="{self._xml_escape(description)}" '
            'adtcore:abapLanguageVersion="cloudDevelopment">'
            f'<adtcore:packageRef adtcore:uri="/sap/bc/adt/packages/{quote(package.lower())}" '
            f'adtcore:type="DEVC/K" adtcore:name="{package.upper()}"/>'
            f'<srvb:services srvb:name="{object_name}">'
            '<srvb:content srvb:version="0001" srvb:minorVersion="0" srvb:patchVersion="0" '
            'srvb:buildVersion="" srvb:releaseState="NOT_RELEASED">'
            f'<srvb:serviceDefinition adtcore:uri="/sap/bc/adt/ddic/srvd/sources/{quote(service_definition_name.lower())}" '
            f'adtcore:type="SRVD/SRV" adtcore:name="{service_definition_name}"/>'
            '<srvb:bindingTypeData><adtcore:content adtcore:encoding="base64"/></srvb:bindingTypeData>'
            '</srvb:content></srvb:services>'
            '<srvb:binding srvb:type="ODATA" srvb:version="V4" srvb:category="0">'
            f'<srvb:implementation adtcore:name="{object_name}"/>'
            '</srvb:binding></srvb:serviceBinding>'
        )
        response = await self._request(
            "POST",
            "/sap/bc/adt/businessservices/bindings",
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/vnd.sap.adt.businessservices.servicebinding.v2+xml; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/vnd.sap.adt.businessservices.servicebinding.v2+xml, application/xml, */*",
        )
        return {
            "created": True,
            "object_type": "SRVB",
            "name": object_name,
            "package": package.upper(),
            "service_definition": service_definition_name,
            "status_code": response.status_code,
            "etag": response.headers.get("etag"),
        }

    async def update_source(self, object_type: str, name: str, source: str, etag: str, reason: str) -> dict[str, Any]:
        self._assert_write_allowed(reason)
        await self._assert_object_write_allowed(object_type, name)
        path = self._source_path(object_type, name)
        content_type = "application/xml; charset=utf-8" if self._is_metadata_write_path(path) else "text/plain; charset=utf-8"
        response = await self._request(
            "PUT",
            path,
            content=source.encode("utf-8"),
            headers={"If-Match": etag, "Content-Type": content_type},
            accept="application/xml, text/plain, */*",
        )
        return {
            "updated": True,
            "object_type": object_type,
            "name": name.upper(),
            "status_code": response.status_code,
            "etag": response.headers.get("etag"),
        }

    async def activate_object(self, object_type: str, name: str, reason: str) -> dict[str, Any]:
        if not self.config.allow_activate:
            raise AuthorizationError("ABAP activation is disabled by configuration")
        if not reason.strip():
            raise ValidationError("Activation reason is required")
        await self._assert_object_write_allowed(object_type, name)
        uri = self._source_path(object_type, name).rsplit("/source/main", 1)[0]
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<adtcore:objectReferences xmlns:adtcore="http://www.sap.com/adt/core">'
            f'<adtcore:objectReference adtcore:uri="{uri}" />'
            "</adtcore:objectReferences>"
        )
        response = await self._request(
            "POST",
            "/sap/bc/adt/activation",
            params={"method": "activate"},
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/xml"},
        )
        return {"activated": True, "object_type": object_type, "name": name.upper(), "status_code": response.status_code}

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

    async def publish_service_binding(self, name: str, reason: str) -> dict[str, Any]:
        self._assert_write_allowed(reason)
        if not reason.strip():
            raise ValidationError("Publish reason is required")
        await self._assert_object_write_allowed("SRVB", name)
        object_name = name.upper()
        metadata = await self.read_source("SRVB", object_name)
        if 'published="true"' in metadata["source"]:
            return {
                "published": True,
                "changed": False,
                "object_type": "SRVB",
                "name": object_name,
                "status_code": metadata.get("status_code", 200),
            }

        uri = f"/sap/bc/adt/businessservices/odatav4/{quote(object_name)}?servicename={quote(object_name)}"
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
            "/sap/bc/adt/businessservices/odatav4/publishjobs",
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
            "status_code": response.status_code,
            "messages": status,
        }

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
                params=params,
                headers=merged_headers,
                content=content,
                follow_redirects=False,
            )
            self._merge_cookies(client.cookies)
        if response.status_code in {401, 403}:
            raise AuthorizationError(
                f"ADT session is not authorized or has expired. SAP returned {response.status_code}; run abap_adt_login again."
            )
        if response.status_code >= 400:
            raise SapBackendError(f"ADT error {response.status_code}: {response.text[:500]}")
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
                headers={"X-CSRF-Token": "Fetch", "Accept": ADT_ACCEPT, **self._reentrance_headers(), **self.session.headers},
                follow_redirects=False,
            )
        if response.status_code in {401, 403}:
            raise AuthorizationError("Cannot fetch ADT CSRF token; SSO session is not authorized or has expired")
        token = response.headers.get("x-csrf-token")
        if not token:
            raise SapBackendError("ADT did not return an X-CSRF-Token")
        return token

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
                headers.setdefault("X-sap-adt-reentrance-ticket", value)
                headers.setdefault("SAP-ADT-ReentranceTicket", value)
                headers.setdefault("MYSAPSSO2", value)
                headers.setdefault("x-sap-security-session", "create")
        return headers

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

    def _source_path(self, object_type: str, name: str) -> str:
        normalized_type = object_type.lower()
        normalized_name = quote(name.lower())
        if normalized_type in {"class", "clas"}:
            return f"/sap/bc/adt/oo/classes/{normalized_name}/source/main"
        if normalized_type in {"interface", "intf"}:
            return f"/sap/bc/adt/oo/interfaces/{normalized_name}/source/main"
        if normalized_type in {"ddls", "cds"}:
            return f"/sap/bc/adt/ddic/ddl/sources/{normalized_name}/source/main"
        if normalized_type in {"dcls", "dcl"}:
            return f"/sap/bc/adt/acm/dcl/sources/{normalized_name}/source/main"
        if normalized_type in {"bdef", "behavior", "behavior_definition"}:
            return f"/sap/bc/adt/bo/behaviordefinitions/{normalized_name}/source/main"
        if normalized_type in {"ddlx", "metadata_extension"}:
            return f"/sap/bc/adt/ddic/ddlx/sources/{normalized_name}/source/main"
        if normalized_type in {"srvd", "service_definition"}:
            return f"/sap/bc/adt/ddic/srvd/sources/{normalized_name}/source/main"
        if normalized_type in {"tabl", "table"}:
            return f"/sap/bc/adt/ddic/tables/{normalized_name}/source/main"
        if normalized_type in {"dtel", "data_element"}:
            return f"/sap/bc/adt/ddic/dataelements/{normalized_name}"
        if normalized_type in {"doma", "domain"}:
            return f"/sap/bc/adt/ddic/domains/{normalized_name}"
        if normalized_type in {"devc", "package"}:
            return f"/sap/bc/adt/packages/{normalized_name}"
        if normalized_type in {"srvb", "service_binding"}:
            return f"/sap/bc/adt/businessservices/bindings/{normalized_name}"
        if normalized_type in {"prog", "program", "prog/p", "report"}:
            return f"/sap/bc/adt/programs/programs/{normalized_name}/source/main"
        if normalized_type in {"fugr", "function_group", "fugr/f"}:
            return f"/sap/bc/adt/functions/groups/{normalized_name}/source/main"
        if normalized_type in {"func", "function_module", "fugr/ff"}:
            group_name, function_name = self._function_module_parts(name)
            return f"/sap/bc/adt/functions/groups/{quote(group_name.lower())}/fmodules/{quote(function_name.lower())}/source/main"
        raise ValidationError(
            "Writable types are class, interface, ddls/cds, dcls/dcl, bdef, ddlx, srvd, srvb, tabl, dtel, doma, devc, prog, fugr, and func"
        )

    def _object_path(self, object_type: str, name: str) -> str:
        source_path = self._source_path(object_type, name)
        return source_path.rsplit("/source/main", 1)[0]

    def _read_path(self, object_type: str, name: str) -> tuple[str, str]:
        normalized_type = object_type.lower().split("/", 1)[0]
        source_part = self._oo_source_part(object_type)
        normalized_name = quote(name.lower())
        if normalized_type in {"class", "clas"}:
            if source_part == "metadata":
                return f"/sap/bc/adt/oo/classes/{normalized_name}", "metadata"
            if source_part == "texts":
                return f"/sap/bc/adt/textelements/classes/{normalized_name}", "metadata"
            return f"/sap/bc/adt/oo/classes/{normalized_name}/{source_part}", "source"
        if normalized_type in {"interface", "intf"}:
            if source_part == "metadata":
                return f"/sap/bc/adt/oo/interfaces/{normalized_name}", "metadata"
            if source_part == "texts":
                return f"/sap/bc/adt/textelements/interfaces/{normalized_name}", "metadata"
            return f"/sap/bc/adt/oo/interfaces/{normalized_name}/{source_part}", "source"
        if normalized_type in {"ddls", "cds"}:
            return f"/sap/bc/adt/ddic/ddl/sources/{normalized_name}/source/main", "source"
        if normalized_type in {"dcls", "dcl"}:
            return f"/sap/bc/adt/acm/dcl/sources/{normalized_name}/source/main", "source"
        if normalized_type in {"bdef", "behavior", "behavior_definition"}:
            return f"/sap/bc/adt/bo/behaviordefinitions/{normalized_name}/source/main", "source"
        if normalized_type in {"ddlx", "metadata_extension"}:
            return f"/sap/bc/adt/ddic/ddlx/sources/{normalized_name}/source/main", "source"
        if normalized_type in {"srvd", "service_definition"}:
            return f"/sap/bc/adt/ddic/srvd/sources/{normalized_name}/source/main", "source"
        if normalized_type in {"tabl", "table"}:
            return f"/sap/bc/adt/ddic/tables/{normalized_name}/source/main", "source"
        if normalized_type in {"dtel", "data_element"}:
            return f"/sap/bc/adt/ddic/dataelements/{normalized_name}", "metadata"
        if normalized_type in {"doma", "domain"}:
            return f"/sap/bc/adt/ddic/domains/{normalized_name}", "metadata"
        if normalized_type in {"devc", "package"}:
            return f"/sap/bc/adt/packages/{normalized_name}", "metadata"
        if normalized_type in {"srvb", "service_binding"}:
            return f"/sap/bc/adt/businessservices/bindings/{normalized_name}", "metadata"
        if normalized_type in {"prog", "program", "prog/p", "report"}:
            return f"/sap/bc/adt/programs/programs/{normalized_name}/source/main", "source"
        if normalized_type in {"fugr", "function_group", "fugr/f"}:
            return f"/sap/bc/adt/functions/groups/{normalized_name}", "metadata"
        if normalized_type in {"func", "function_module", "fugr/ff"}:
            group_name, function_name = self._function_module_parts(name)
            return f"/sap/bc/adt/functions/groups/{quote(group_name.lower())}/fmodules/{quote(function_name.lower())}/source/main", "source"
        raise ValidationError(
            "Supported read types are class, interface, ddls/cds, dcls/dcl, bdef, ddlx, srvd, tabl, dtel, doma, devc, srvb, prog, fugr, and func"
        )

    def _is_oo_source_type(self, object_type: str) -> bool:
        normalized_type = object_type.lower().split("/", 1)[0]
        return normalized_type in {"class", "clas", "interface", "intf"}

    def _is_source_search_type(self, object_type: str) -> bool:
        normalized_type = object_type.lower().split("/", 1)[0]
        return normalized_type in {
            "class",
            "clas",
            "interface",
            "intf",
            "ddls",
            "cds",
            "dcls",
            "dcl",
            "bdef",
            "behavior",
            "behavior_definition",
            "ddlx",
            "metadata_extension",
            "srvd",
            "service_definition",
            "tabl",
            "table",
            "dtel",
            "data_element",
            "doma",
            "domain",
            "prog",
            "program",
            "report",
            "fugr",
            "function_group",
            "func",
            "function_module",
        }

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

    def _oo_source_part(self, object_type: str) -> str:
        parts = object_type.lower().split("/")
        if len(parts) < 2:
            return "source/main"
        requested = parts[-1].replace("-", "_")
        include_parts = {
            "main": "source/main",
            "source": "source/main",
            "definitions": "includes/definitions",
            "definition": "includes/definitions",
            "local_definitions": "includes/definitions",
            "implementations": "includes/implementations",
            "implementation": "includes/implementations",
            "local_implementations": "includes/implementations",
            "macros": "includes/macros",
            "testclasses": "includes/testclasses",
            "test_classes": "includes/testclasses",
            "tests": "includes/testclasses",
            "metadata": "metadata",
            "json": "metadata",
            "texts": "texts",
            "textelements": "texts",
            "text_elements": "texts",
        }
        return include_parts.get(requested, "source/main")

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
                }
            )

        if len(parts) == 1:
            return result

        result["source_kind"] = "source_with_includes"
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

    def _adt_relative_url(self, base_path: str, href: str) -> str:
        if href.startswith("/"):
            return href
        return "/" + urljoin(base_path.lstrip("/"), href).lstrip("/")

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
        normalized_type = object_type.lower().split("/", 1)[0]
        search_name = name
        if normalized_type in {"func", "function_module"}:
            search_name, _ = self._function_module_parts(name)
        search_type = {
            "class": "CLAS",
            "clas": "CLAS",
            "interface": "INTF",
            "intf": "INTF",
            "ddls": "DDLS",
            "cds": "DDLS",
            "bdef": "BDEF",
            "behavior": "BDEF",
            "behavior_definition": "BDEF",
            "ddlx": "DDLX",
            "metadata_extension": "DDLX",
            "srvd": "SRVD",
            "service_definition": "SRVD",
            "tabl": "TABL",
            "table": "TABL",
            "dtel": "DTEL",
            "data_element": "DTEL",
            "doma": "DOMA",
            "domain": "DOMA",
            "srvb": "SRVB",
            "service_binding": "SRVB",
            "prog": "PROG",
            "program": "PROG",
            "report": "PROG",
            "fugr": "FUGR",
            "function_group": "FUGR",
            "func": "FUGR",
            "function_module": "FUGR",
        }.get(normalized_type, object_type.upper().split("/", 1)[0])
        try:
            results = await self._search_repository_objects(search_name, 20, search_type, None)
        except Exception:
            return None
        object_name = search_name.upper()
        for item in results:
            if item.get("name", "").upper() == object_name and item.get("packageName"):
                return item["packageName"]
        return None

    def _function_module_parts(self, name: str) -> tuple[str, str]:
        if "/" not in name:
            raise ValidationError("Function module source paths require name in FUNCTION_GROUP/FUNCTION_MODULE format")
        group_name, function_name = name.split("/", 1)
        if not group_name.strip() or not function_name.strip():
            raise ValidationError("Function module source paths require name in FUNCTION_GROUP/FUNCTION_MODULE format")
        return group_name.strip().upper(), function_name.strip().upper()

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

    def _is_metadata_write_path(self, path: str) -> bool:
        return not path.endswith("/source/main")

    def _server_etag_from_precondition(self, message: str) -> str | None:
        match = re.search(r"does not match the object ETag ([^\s<]+)", message)
        return match.group(1) if match else None

    def _parse_status_messages(self, text: str) -> list[dict[str, str]]:
        if not text.strip():
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return [{"text": text}]
        messages: list[dict[str, str]] = []
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1].lower()
            if tag not in {"message", "statusmessage", "status"}:
                continue
            item = {self._clean_xml_name(key).lower(): value for key, value in element.attrib.items()}
            if element.text and element.text.strip():
                item["text"] = element.text.strip()
            if item:
                messages.append(item)
        return messages
