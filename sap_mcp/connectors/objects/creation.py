from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from sap_mcp.connectors.core.base import BaseMixin
from sap_mcp.connectors.core.constants import CREATABLE_OBJECT_TYPES
from sap_mcp.connectors.core.registry import (
    ADT_BASE_PATH,
    SUPPORTED_WRITABLE_TYPES_HELP,
    AdtPathRegistration,
    AdtResponse,
)
from sap_mcp.connectors.objects.creation_strategies import STRATEGY_REGISTRY
from sap_mcp.connectors.objects.lock import LockMixin
from sap_mcp.errors import SapBackendError, ValidationError


class AdtCreationMixin(LockMixin, BaseMixin):
    async def create_object(
        self,
        object_type: str,
        name: str,
        package: str,
        description: str,
        reason: str,
        source: str | None = None,
        service_binding_version: str | None = None,
        transport_request_number: str | None = None,
        implementation_type: str | None = None,
    ) -> dict[str, Any]:
        self._assert_write_allowed(reason)
        self._assert_package_allowed(package)
        registration = self._path_registration(object_type, SUPPORTED_WRITABLE_TYPES_HELP)
        initial_source = source if source is not None else self._default_creation_source(registration.canonical_type, name, description)
        strategy = STRATEGY_REGISTRY.get(registration.canonical_type)
        if strategy is not None:
            return await strategy.create(
                self, registration, name, package, description, initial_source, reason,
                service_binding_version=service_binding_version,
                transport_request_number=transport_request_number,
                implementation_type=implementation_type,
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
        metadata = self._repository_metadata_xml(
            "package:package",
            'xmlns:package="http://www.sap.com/adt/packages"',
            object_name,
            "DEVC/K",
            description,
            parent_package,
            abap_language_version=None,
        )
        response = await self._request(
            "POST",
            self._collection_path(registration.canonical_type),
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
        transport_request_number: str | None = None,
    ) -> dict[str, Any]:
        if not getattr(registration, 'create_xml_name', None) or not getattr(registration, 'create_xml_namespace', None) or not getattr(registration, 'create_adt_type', None):
            raise ValidationError(f"{getattr(registration, 'display_name', registration.canonical_type)} does not define metadata creation XML")
        object_name = name.upper()
        metadata = self._repository_metadata_xml(
            registration.create_xml_name,
            registration.create_xml_namespace,
            object_name,
            registration.create_adt_type,
            description,
            package,
            abap_language_version=getattr(registration, 'create_abap_language_version', None),
            extra_attrs=getattr(registration, 'create_xml_extra_attrs', None),
        )
        content_type = getattr(registration, 'create_content_type', None) or "application/xml; charset=utf-8"
        accept = getattr(registration, 'create_accept', None) or "application/xml, application/*, */*"
        response = await self._request(
            "POST",
            self._collection_path(registration.canonical_type),
            params=self._creation_corrnr_params(transport_request_number),
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": content_type,
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept=accept,
        )
        return self._created_result(registration.canonical_type, object_name, package, response)

    def _creation_corrnr_params(self, transport_request_number: str | None) -> dict[str, str] | None:
        request_number = (transport_request_number or "").strip().upper()
        return {"corrNr": request_number} if request_number else None

    async def _create_domain(
        self, registration: AdtPathRegistration, name: str, package: str, description: str
    ) -> dict[str, Any]:
        object_name = name.upper()
        metadata = self._dictionary_blue_xml(
            "http://www.sap.com/wbobj/dictionary/doma",
            object_name,
            "DOMA/DM",
            description,
            package,
            '<doma:domain xmlns:doma="http://www.sap.com/adt/dictionary/domains">'
            "<doma:dataType>CHAR</doma:dataType><doma:dataTypeLength>000001</doma:dataTypeLength>"
            "<doma:dataTypeDecimals>000000</doma:dataTypeDecimals>"
            "<doma:outputLength>000001</doma:outputLength><doma:conversionExit/>"
            "</doma:domain>",
        )
        response = await self._request(
            "POST",
            self._collection_path(registration.canonical_type),
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
        group_name = function_group.strip().upper()
        object_name = name.upper()
        if "/" in object_name and not group_name:
            group_name, object_name = self._function_module_parts(object_name)
        if not group_name:
            raise ValidationError("Function module creation requires source to contain the function group name")
        await self._assert_object_write_allowed("FUGR", group_name)
        metadata = self._repository_metadata_xml(
            "fmodule:abapFunctionModule",
            'xmlns:fmodule="http://www.sap.com/adt/functions/fmodules"',
            object_name,
            "FUGR/FF",
            description,
            package,
            self._container_ref_xml(f"{ADT_BASE_PATH}/functions/groups/{quote(group_name.lower())}", "FUGR/F", group_name),
            abap_language_version=None,
            include_package_ref=False,
        )
        response = await self._request(
            "POST",
            self._collection_path(registration.canonical_type, f"{group_name}/{object_name}"),
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/xml; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/xml, application/*, */*",
        )
        return self._created_result("FUNC", object_name, package, response, function_group=group_name)

    async def _create_data_element(
        self, registration: AdtPathRegistration, name: str, package: str, description: str
    ) -> dict[str, Any]:
        object_name = name.upper()
        label = self._xml_escape(description)
        metadata = self._dictionary_blue_xml(
            "http://www.sap.com/wbobj/dictionary/dtel",
            object_name,
            "DTEL/DE",
            description,
            package,
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
            "</dtel:dataElement>",
        )
        response = await self._request(
            "POST",
            self._collection_path(registration.canonical_type),
            content=metadata.encode("utf-8"),
            headers={
                "Content-Type": "application/vnd.sap.adt.dataelements.v2+xml; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(),
                "X-SAP-ADT-Description": description,
            },
            accept="application/vnd.sap.adt.dataelements.v2+xml, application/xml, */*",
        )
        return self._created_result("DTEL", object_name, package, response)

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
        service_definition_exists = await self.object_exists("SRVD", service_definition_name)
        if not service_definition_exists["exists"]:
            raise ValidationError(
                f"Service binding {object_name} requires existing service definition {service_definition_name}. "
                "Create/activate the SRVD first, then retry SRVB creation."
            )
        odata_version = self._normalize_odata_version(service_binding_version, default="V4")
        metadata = self._repository_metadata_xml(
            "srvb:serviceBinding",
            'xmlns:srvb="http://www.sap.com/adt/ddic/ServiceBindings" srvb:bindingCreated="false"',
            object_name,
            "SRVB/SVB",
            description,
            package,
            f'<srvb:services srvb:name="{object_name}">'
            '<srvb:content srvb:version="0001" srvb:minorVersion="0" srvb:patchVersion="0" '
            'srvb:buildVersion="" srvb:releaseState="NOT_RELEASED">'
            f'<srvb:serviceDefinition adtcore:uri="{ADT_BASE_PATH}/ddic/srvd/sources/{quote(service_definition_name.lower())}" '
            f'adtcore:type="SRVD/SRV" adtcore:name="{service_definition_name}"/>'
            '<srvb:bindingTypeData><adtcore:content adtcore:encoding="base64"/></srvb:bindingTypeData>'
            '</srvb:content></srvb:services>'
            f'<srvb:binding srvb:type="ODATA" srvb:version="{odata_version}" srvb:category="0">'
            f'<srvb:implementation adtcore:name="{object_name}"/>'
            '</srvb:binding>',
        )
        response = await self._request(
            "POST",
            self._collection_path(registration.canonical_type),
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

    async def _created_with_pending_source(
        self,
        object_type: str,
        object_name: str,
        package: str,
        create_response: dict[str, Any],
        source_path: str,
        error: SapBackendError,
    ) -> dict[str, Any]:
        exists = await self.object_exists(object_type, object_name)
        if not exists["exists"]:
            raise error
        result = dict(create_response)
        result["source_written"] = False
        result["warning"] = (
            "Object was created, but source update failed. Read the source to get the current writable_etag, "
            "then call abap_update_source. On OP systems, pass the same transport_request_number used for creation."
        )
        result["writable_uri"] = source_path
        result["error"] = str(error)
        result["details"] = error.details
        request_number = self._transport_request_from_error(error)
        if request_number:
            result["transport_request_number"] = request_number
        return result

    @staticmethod
    def _transport_request_from_error(error: SapBackendError) -> str | None:
        text = " ".join(
            str(value or "")
            for value in (
                error,
                error.details.get("html_summary"),
                error.details.get("raw_excerpt"),
            )
        )
        match = re.search(r"\brequest\s+([A-Z0-9]{3}K\d{6})\b", text, re.IGNORECASE)
        return match.group(1).upper() if match else None

    def _default_creation_source(self, object_type: str, name: str, description: str) -> str:
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
        if normalized_type in {"fugr", "fugr/f", "function_group"}:
            return ""
        if normalized_type in {"func", "function_module", "fugr/ff"}:
            return ""
        if normalized_type in {"tabl", "table"}:
            return (
                f"@EndUserText.label : '{description}'\n"
                "@AbapCatalog.enhancement.category : #NOT_EXTENSIBLE\n"
                "@AbapCatalog.tableCategory : #TRANSPARENT\n"
                "@AbapCatalog.deliveryClass : #A\n"
                "@AbapCatalog.dataMaintenance : #RESTRICTED\n"
                f"define table {object_name.lower()} {{\n"
                "  key client : abap.clnt not null;\n"
                "  key id     : abap.char(1) not null;\n"
                "}\n"
            )
        if normalized_type in {"dtel", "data_element", "doma", "domain", "devc", "package"}:
            return ""
        raise ValidationError(SUPPORTED_WRITABLE_TYPES_HELP)

    def _created_result(
        self,
        object_type: str,
        name: str,
        package: str,
        response: AdtResponse,
        **extra: Any,
    ) -> dict[str, Any]:
        extra.setdefault("parameter_set", "simple")
        writable_uri = self._source_path(object_type, name)
        etag = self._normalized_etag(response.headers.get("etag"), response.content_type)
        return {
            "created": True,
            "object_type": object_type,
            "name": name.upper(),
            **extra,
            "package": package.upper(),
            "status_code": response.status_code,
            "etag": etag,
            "writable_etag": etag,
            "writable_uri": writable_uri,
        }

    # ── Lock-based source write (delegates to LockMixin) ──

    def _lock_endpoint_uri(self, object_type: str, name: str) -> str:
        return self._resolve_registration_path(
            self._path_registration(object_type, SUPPORTED_WRITABLE_TYPES_HELP), name,
        )

    async def _lock_put_unlock_source(
        self, object_type: str, name: str, package: str, description: str, source: str,
        transport_request_number: str | None = None,
    ) -> dict[str, Any]:
        uri = self._lock_endpoint_uri(object_type, name)
        handle = await self._lock_object(uri)
        try:
            response = await self._request(
                "PUT", self._source_path(object_type, name),
                params={"lockHandle": handle, **(self._creation_corrnr_params(transport_request_number) or {})},
                content=source.encode("utf-8"),
                headers={
                    **self._stateful_headers(),
                    "Content-Type": "text/plain; charset=utf-8",
                    "X-SAP-ADT-Package": package.upper(),
                    "X-SAP-ADT-Description": description,
                },
                accept="application/xml, text/plain, */*",
            )
            return {"source_written": True, **self._created_result(object_type, name, package, response)}
        finally:
            await self._unlock_object(uri, handle)


class CreationMixin(BaseMixin):
    """Schema-driven creation info: list creatable types, type details, validation."""

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
                {"name": item["name"], "adt_object_type": object_type, "object_type": object_type.split("/", 1)[0]}
                for object_type, item in sorted(CREATABLE_OBJECT_TYPES.items())
            ]
        return {"creatable_objects": objects}

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
            {"name": "name", "required": True, "value": name or "", "max_length": details["max_len"]},
            {"name": "description", "required": True, "value": description or ""},
            {"name": "packageName", "required": True, "value": ""},
        ]
        if object_type_id == "FUGR/FF":
            fields.append({"name": "parentName", "required": True, "value": ""})
        if object_type_id == "SRVB/SVB":
            fields.extend([
                {"name": "serviceDefinition", "required": True, "value": ""},
                {"name": "serviceBindingVersion", "required": False, "value": "ODATA\\V2"},
            ])
        if object_type_id == "DEVC/K":
            fields.extend([
                {"name": "softwareComponent", "required": False, "value": ""},
                {"name": "transportLayer", "required": False, "value": ""},
                {"name": "packageType", "required": False, "value": "development"},
            ])
        return {
            "adt_object_type": object_type_id,
            "object_type": object_type_id.split("/", 1)[0],
            "accepted_object_types": [object_type_id, object_type_id.split("/", 1)[0]],
            "name": details["name"],
            "fields": fields,
            "parameter_sets": self._creation_parameter_sets(object_type_id),
            "recording_required": True,
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
        result = {"message": message, "severity": severity or "OK", "recording_required": package_name.upper() != "$TMP"}
        if severity in {"ERROR", "A", "E", "X"}:
            result["error"] = message
        return result

    async def creation_create_object(
        self,
        destination: str,
        object_type: str,
        object_content: str,
        transport_request_number: str | None = None,
    ) -> dict[str, Any]:
        self._assert_destination(destination)
        content = self._object_content(object_content)
        object_type_id = self._creatable_type_id(object_type)
        object_name = self._required_content(content, "name")
        description = self._required_content(content, "description")
        package_name = self._required_content(content, "packageName", "package", "developmentPackage")
        source = str(content.get("source") or "")
        service_binding_version = content.get("serviceBindingVersion") or None
        implementation_type = content.get("implementationType") or None
        try:
            result = await self.create_object(
                object_type=object_type_id,
                name=object_name,
                package=package_name,
                description=description,
                reason="Create object through ADT-compatible creation workflow",
                source=source if source else None,
                service_binding_version=service_binding_version,
                transport_request_number=transport_request_number,
                implementation_type=implementation_type,
            )
        except SapBackendError as error:
            return {
                "message": f"{object_type_id} {object_name.upper()} creation failed",
                "error": str(error),
                "details": error.details,
                "adt_object_type": object_type_id,
                "object_type": object_type_id.split("/", 1)[0],
                "object_name": object_name.upper(),
                "file_path": self._created_object_path(object_type_id, object_name, content),
                "parameter_set": "schema",
            }
        if result.get("created"):
            return {
                "message": f"{object_type_id} {object_name.upper()} created",
                "file_path": self._created_object_path(object_type_id, object_name, content),
                "status_code": result.get("status_code", 200),
                "etag": result.get("etag", ""),
                "recording_required": bool(transport_request_number),
                "adt_object_type": object_type_id,
                "object_type": object_type_id.split("/", 1)[0],
                "parameter_set": "schema",
            }
        return {
            "message": f"{object_type_id} {object_name.upper()} creation failed",
            "error": result.get("error", "Unknown error"),
            "details": result.get("details"),
            "adt_object_type": object_type_id,
            "object_type": object_type_id.split("/", 1)[0],
            "object_name": object_name.upper(),
            "file_path": self._created_object_path(object_type_id, object_name, content),
            "parameter_set": "schema",
        }

    def _creation_corrnr_params(self, transport_request_number: str | None) -> dict[str, str] | None:
        return {"corrNr": transport_request_number} if transport_request_number else None

    def _creation_parameter_sets(self, object_type: str) -> list[dict[str, Any]]:
        base_type = object_type.split("/", 1)[0]
        sets = [
            {
                "mode": "schema",
                "parameters": ["object_type", "object_content", "destination"],
                "optional": ["transport_request_number"],
            }
        ]
        if base_type in {"CLAS", "INTF", "DDLS", "DCLS", "BDEF", "DDLX", "SRVD", "TABL", "DTEL", "DOMA", "DEVC", "PROG", "FUGR", "FUNC"}:
            sets.insert(0, {
                "mode": "simple",
                "parameters": ["object_type", "name", "package", "description"],
                "optional": ["source"],
            })
        if base_type == "SRVB":
            sets.insert(0, {
                "mode": "simple",
                "parameters": ["object_type", "name", "package", "description"],
                "optional": ["source as service definition name", "service_binding_version"],
                "default_rule": "When source is omitted, SRVB creation links to an existing SRVD with the same name.",
            })
        return sets

    def _parse_type_structure(self, text: str) -> list[dict[str, str]]:
        root = ET.fromstring(text)
        objects = []
        for element in root.iter():
            if self._xml_local_name(element.tag) != "SEU_ADT_OBJECT_TYPE_DESCRIPTOR":
                continue
            record = self._direct_child_texts(element)
            object_type = record.get("OBJECT_TYPE")
            if object_type:
                objects.append({
                    "name": record.get("OBJECT_TYPE_LABEL") or CREATABLE_OBJECT_TYPES.get(object_type, {}).get("name", object_type),
                    "adt_object_type": object_type,
                    "object_type": object_type.split("/", 1)[0],
                })
        return objects

    def _validation_params(
        self, object_type: str, object_name: str, description: str, package_name: str, content: dict[str, Any]
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

    def _created_object_path(self, object_type: str, object_name: str, content: dict[str, Any]) -> str:
        details = self._creatable_type(object_type)
        creation_path = details["creation_path"].format(parent=quote(str(content.get("parentName") or "").lower()))
        return f"/sap/bc/adt/{creation_path}/{quote(object_name.lower())}"
