from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

from sap_mcp.errors import ValidationError
from sap_mcp.security import SYSTEM_USER

if TYPE_CHECKING:
    from sap_mcp.services.abap_dev_gateway import AbapDevGateway


def register_workflow_tools(mcp: FastMCP, abap_gateway: AbapDevGateway) -> None:
    @mcp.tool()
    async def abap_list_destinations() -> list[str]:
        """Get list of available ABAP system destinations."""
        return await abap_gateway.list_destinations(SYSTEM_USER)

    @mcp.tool(name="abap_creation_info")
    async def abap_creation_info(
        action: str,
        destination: str,
        object_type: str | None = None,
        object_content: str | dict[str, Any] | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Inspect or validate object creation metadata. action: list_types, type_details, or validate."""
        normalized = action.strip().lower()
        if normalized == "list_types":
            return await abap_gateway.creation_get_all_creatable_objects(SYSTEM_USER, destination)
        if normalized == "type_details":
            if not object_type:
                raise ValidationError("object_type is required when action=type_details")
            return await abap_gateway.creation_get_object_type_details(SYSTEM_USER, destination, object_type, name, description)
        if normalized == "validate":
            if not object_type or not object_content:
                raise ValidationError("object_type and object_content are required when action=validate")
            return await abap_gateway.creation_run_validation(SYSTEM_USER, destination, object_type, object_content)
        raise ValidationError("action must be one of: list_types, type_details, validate")

    @mcp.tool(name="abap_generators")
    async def abap_generators(
        action: str,
        destination: str,
        generator_id: str | None = None,
        package_name: str | None = None,
        referenced_object_type: str = "",
        referenced_object_name: str = "",
        content: str | None = None,
        transport_request_number: str | None = None,
    ) -> dict[str, Any]:
        """Work with RAP generators. action: list, schema, or generate.
        Note: package_name is required for schema and generate actions."""
        normalized = action.strip().lower()
        if normalized == "list":
            return await abap_gateway.generators_list_generators(SYSTEM_USER, destination)
        if not generator_id or package_name is None:
            raise ValidationError("generator_id and package_name are required when action is schema or generate")
        if normalized == "schema":
            return await abap_gateway.generators_get_schema(
                SYSTEM_USER, destination, generator_id, package_name, referenced_object_type, referenced_object_name
            )
        if normalized == "generate":
            if content is None or transport_request_number is None:
                raise ValidationError("content and transport_request_number are required when action=generate")
            return await abap_gateway.generators_generate_objects(
                SYSTEM_USER,
                destination,
                generator_id,
                content,
                package_name,
                transport_request_number,
                referenced_object_type,
                referenced_object_name,
            )
        raise ValidationError("action must be one of: list, schema, generate")

    @mcp.tool(name="abap_transport")
    async def abap_transport(
        action: str,
        destination: str,
        development_package: str,
        is_creation: bool,
        object_name: str | None = None,
        object_type: str | None = None,
        transport_description: str | None = None,
        transport_request_number: str | None = None,
    ) -> dict[str, Any]:
        """Manage transport selection for object workflows. action: get, create, list_tasks, objects, or release."""
        normalized = action.strip().lower()
        if normalized == "get":
            if not object_name or not object_type:
                raise ValidationError("object_name and object_type are required when action=get")
            return await abap_gateway.transport_get(
                SYSTEM_USER, destination, object_name, object_type, development_package, is_creation
            )
        if normalized == "create":
            if not transport_description:
                raise ValidationError("transport_description is required when action=create")
            return await abap_gateway.transport_create(
                SYSTEM_USER,
                destination,
                development_package,
                transport_description,
                is_creation,
                object_name,
                object_type,
            )
        if normalized == "list_tasks":
            if not transport_request_number:
                raise ValidationError("transport_request_number is required when action=list_tasks")
            return await abap_gateway.transport_list_tasks(SYSTEM_USER, transport_request_number)
        if normalized == "objects":
            if not transport_request_number:
                raise ValidationError("transport_request_number is required when action=objects")
            return await abap_gateway.transport_list_objects(SYSTEM_USER, transport_request_number)
        if normalized == "release":
            if not transport_request_number:
                raise ValidationError("transport_request_number is required when action=release")
            return await abap_gateway.transport_release(SYSTEM_USER, transport_request_number)
        raise ValidationError("action must be get, create, list_tasks, objects, or release")

    @mcp.tool(name="abap_lock")
    async def abap_lock(
        object_url: str,
        is_creation: bool = False,
    ) -> dict[str, Any]:
        """Lock an ABAP object via the ADT Lock API (POST /sap/bc/adt/locks). Returns lock_handle, corrnr (transport request number), and owner. For $TMP package objects, corrnr is empty. Lock should be released with abap_unlock after write operations."""
        return await abap_gateway.lock_object(SYSTEM_USER, object_url, is_creation)

    @mcp.tool(name="abap_unlock")
    async def abap_unlock(
        lock_handle: str,
        object_url: str,
    ) -> dict[str, Any]:
        """Release an ADT object lock (DELETE /sap/bc/adt/locks). Pass the lock_handle and object_url returned by abap_lock."""
        await abap_gateway.unlock_object(SYSTEM_USER, lock_handle, object_url)
        return {"unlocked": True, "object_url": object_url}

    @mcp.tool(name="abap_business_services")
    async def abap_business_services(
        action: str,
        service_binding_name: str,
        destination: str,
        service_name: str | None = None,
        service_definition: str | None = None,
        service_version: str | None = None,
        odata_info_uri: str | None = None,
        odata_version: str | None = None,
        is_published: bool | None = None,
    ) -> dict[str, Any]:
        """Read service binding OData data. action: list_services or service_info."""
        normalized = action.strip().lower()
        if normalized == "list_services":
            return await abap_gateway.business_services_fetch_services(SYSTEM_USER, destination, service_binding_name)
        if normalized == "service_info":
            return await abap_gateway.business_services_fetch_service_information(
                SYSTEM_USER,
                destination,
                service_binding_name,
                service_name,
                service_definition,
                service_version,
                odata_info_uri,
                odata_version,
                is_published,
            )
        raise ValidationError("action must be list_services or service_info")
