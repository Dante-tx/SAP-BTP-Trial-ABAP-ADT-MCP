from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

from sap_mcp.security import SYSTEM_USER

if TYPE_CHECKING:
    from sap_mcp.services.abap_dev_gateway import AbapDevGateway


def register_official_tools(mcp: FastMCP, abap_gateway: AbapDevGateway) -> None:
    @mcp.tool()
    async def abap_list_destinations() -> list[str]:
        """Get list of available ABAP system destinations."""
        return await abap_gateway.list_destinations(SYSTEM_USER)

    @mcp.tool(name="abap_creation-get_all_creatable_objects")
    async def abap_creation_get_all_creatable_objects(destination: str) -> dict[str, Any]:
        """Get all ABAP object types creatable for a destination."""
        return await abap_gateway.creation_get_all_creatable_objects(SYSTEM_USER, destination)

    @mcp.tool(name="abap_creation-get_object_type_details")
    async def abap_creation_get_object_type_details(
        objectType: str,
        destination: str,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Get field details required to create one ABAP object type."""
        return await abap_gateway.creation_get_object_type_details(SYSTEM_USER, destination, objectType, name, description)

    @mcp.tool(name="abap_creation-run_validation")
    async def abap_creation_run_validation(destination: str, objectType: str, objectContent: str) -> dict[str, Any]:
        """Validate ABAP object creation input before creation."""
        return await abap_gateway.creation_run_validation(SYSTEM_USER, destination, objectType, objectContent)

    @mcp.tool(name="abap_creation-create_object")
    async def abap_creation_create_object(
        destination: str,
        objectType: str,
        objectContent: str,
        transportRequestNumber: str,
    ) -> dict[str, Any]:
        """Create an ABAP object with transport-aware workflow parameters."""
        return await abap_gateway.creation_create_object(SYSTEM_USER, destination, objectType, objectContent, transportRequestNumber)

    @mcp.tool(name="abap_generators-list_generators")
    async def abap_generators_list_generators(destination: str) -> dict[str, Any]:
        """List available ABAP RAP generators."""
        return await abap_gateway.generators_list_generators(SYSTEM_USER, destination)

    @mcp.tool(name="abap_generators-get_schema")
    async def abap_generators_get_schema(
        destination: str,
        generatorId: str,
        packageName: str,
        referencedObjectType: str,
        referencedObjectName: str,
    ) -> dict[str, Any]:
        """Get JSON schema and reference content for a RAP generator."""
        return await abap_gateway.generators_get_schema(
            SYSTEM_USER, destination, generatorId, packageName, referencedObjectType, referencedObjectName
        )

    @mcp.tool(name="abap_generators-generate_objects")
    async def abap_generators_generate_objects(
        destination: str,
        generatorId: str,
        content: str,
        packageName: str,
        transportRequestNumber: str,
        referencedObjectType: str,
        referencedObjectName: str,
    ) -> dict[str, Any]:
        """Validate and generate RAP objects."""
        return await abap_gateway.generators_generate_objects(
            SYSTEM_USER,
            destination,
            generatorId,
            content,
            packageName,
            transportRequestNumber,
            referencedObjectType,
            referencedObjectName,
        )

    @mcp.tool(name="abap_transport-get")
    async def abap_transport_get(
        destination: str,
        objectName: str,
        objectType: str,
        developmentPackage: str,
        isCreation: bool,
    ) -> dict[str, Any]:
        """Validate transport recording and list relevant transport requests."""
        return await abap_gateway.transport_get(SYSTEM_USER, destination, objectName, objectType, developmentPackage, isCreation)

    @mcp.tool(name="abap_transport-create")
    async def abap_transport_create(
        destination: str,
        developmentPackage: str,
        transportDescription: str,
        isCreation: bool,
        objectName: str | None = None,
        objectType: str | None = None,
    ) -> dict[str, Any]:
        """Create a transport request for an ABAP object workflow."""
        return await abap_gateway.transport_create(
            SYSTEM_USER,
            destination,
            developmentPackage,
            transportDescription,
            isCreation,
            objectName,
            objectType,
        )

    @mcp.tool(name="abap_business_services-fetch_services")
    async def abap_business_services_fetch_services(serviceBindingName: str, destination: str) -> dict[str, Any]:
        """Fetch OData services exposed by a service binding."""
        return await abap_gateway.business_services_fetch_services(SYSTEM_USER, destination, serviceBindingName)

    @mcp.tool(name="abap_business_services-fetch_service_information")
    async def abap_business_services_fetch_service_information(
        serviceBindingName: str,
        destination: str,
        serviceName: str | None = None,
        serviceDefinition: str | None = None,
        serviceVersion: str | None = None,
        odataInfoUri: str | None = None,
        odataVersion: str | None = None,
        isPublished: bool | None = None,
    ) -> dict[str, Any]:
        """Fetch runtime URL, entity sets, and navigation details for an OData service.

        When service details are omitted, they are derived from the service binding metadata.
        """
        return await abap_gateway.business_services_fetch_service_information(
            SYSTEM_USER,
            destination,
            serviceBindingName,
            serviceName,
            serviceDefinition,
            serviceVersion,
            odataInfoUri,
            odataVersion,
            isPublished,
        )
