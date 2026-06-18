from __future__ import annotations

from typing import Any

from sap_mcp.security import UserContext


class OfficialGatewayMixin:
    async def list_destinations(self, user: UserContext) -> list[str]:
        return await self._run_with_connector(
            user,
            "abap_list_destinations",
            lambda connector: connector.list_destinations(),
            expired_message="The saved SSO session expired while listing ABAP destinations.",
        )

    async def activate_uris(self, user: UserContext, uris: list[str], reason: str) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_activate_objects",
            lambda connector: connector.activate_objects(connector.official_uri_objects(uris), reason),
            expired_message="The saved SSO session expired while activating ABAP objects.",
            write=True,
        )

    async def run_unit_tests_for_uris(
        self,
        user: UserContext,
        uris: list[str],
        include_subpackages: bool = True,
        title: str = "MCP ABAP Unit Run",
        wait_seconds: int = 0,
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_run_unit_tests",
            lambda connector: connector.run_unit_tests(
                connector.official_uri_objects(uris), None, include_subpackages, title, wait_seconds
            ),
            quality_action="running ABAP Unit tests",
        )

    async def creation_get_all_creatable_objects(self, user: UserContext, destination: str) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_creation-get_all_creatable_objects",
            lambda connector: connector.creation_get_all_creatable_objects(destination),
            expired_message="The saved SSO session expired while listing creatable ABAP object types.",
        )

    async def creation_get_object_type_details(
        self,
        user: UserContext,
        destination: str,
        object_type: str,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_creation-get_object_type_details",
            lambda connector: connector.creation_get_object_type_details(destination, object_type, name, description),
            expired_message="The saved SSO session expired while reading ABAP object creation details.",
        )

    async def creation_run_validation(self, user: UserContext, destination: str, object_type: str, object_content: str) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_creation-run_validation",
            lambda connector: connector.creation_run_validation(destination, object_type, object_content),
            expired_message="The saved SSO session expired while validating ABAP object creation.",
        )

    async def creation_create_object(
        self,
        user: UserContext,
        destination: str,
        object_type: str,
        object_content: str,
        transport_request_number: str,
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_creation-create_object",
            lambda connector: connector.creation_create_object(destination, object_type, object_content, transport_request_number),
            expired_message="The saved SSO session expired while creating the ABAP object.",
            write=True,
        )

    async def generators_list_generators(self, user: UserContext, destination: str) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_generators-list_generators",
            lambda connector: connector.generators_list_generators(destination),
            expired_message="The saved SSO session expired while listing RAP generators.",
        )

    async def generators_get_schema(
        self,
        user: UserContext,
        destination: str,
        generator_id: str,
        package_name: str,
        referenced_object_type: str,
        referenced_object_name: str,
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_generators-get_schema",
            lambda connector: connector.generators_get_schema(
                destination, generator_id, package_name, referenced_object_type, referenced_object_name
            ),
            expired_message="The saved SSO session expired while reading the RAP generator schema.",
        )

    async def generators_generate_objects(
        self,
        user: UserContext,
        destination: str,
        generator_id: str,
        content: str,
        package_name: str,
        transport_request_number: str,
        referenced_object_type: str,
        referenced_object_name: str,
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_generators-generate_objects",
            lambda connector: connector.generators_generate_objects(
                destination,
                generator_id,
                content,
                package_name,
                transport_request_number,
                referenced_object_type,
                referenced_object_name,
            ),
            expired_message="The saved SSO session expired while generating RAP objects.",
            write=True,
        )

    async def transport_get(
        self,
        user: UserContext,
        destination: str,
        object_name: str,
        object_type: str,
        development_package: str,
        is_creation: bool,
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_transport-get",
            lambda connector: connector.transport_get(destination, object_name, object_type, development_package, is_creation),
            expired_message="The saved SSO session expired while reading transport requests.",
        )

    async def transport_create(
        self,
        user: UserContext,
        destination: str,
        development_package: str,
        transport_description: str,
        is_creation: bool,
        object_name: str | None = None,
        object_type: str | None = None,
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_transport-create",
            lambda connector: connector.transport_create(
                destination, development_package, transport_description, is_creation, object_name, object_type
            ),
            expired_message="The saved SSO session expired while creating the transport request.",
            write=True,
        )

    async def business_services_fetch_services(
        self, user: UserContext, destination: str, service_binding_name: str
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_business_services-fetch_services",
            lambda connector: connector.business_services_fetch_services(destination, service_binding_name),
            expired_message="The saved SSO session expired while reading business services.",
        )

    async def business_services_fetch_service_information(
        self,
        user: UserContext,
        destination: str,
        service_binding_name: str,
        service_name: str | None = None,
        service_definition: str | None = None,
        service_version: str | None = None,
        odata_info_uri: str | None = None,
        odata_version: str | None = None,
        is_published: bool | None = None,
    ) -> dict[str, Any]:
        return await self._run_with_connector(
            user,
            "abap_business_services-fetch_service_information",
            lambda connector: connector.business_services_fetch_service_information(
                destination,
                service_binding_name,
                service_name,
                service_definition,
                service_version,
                odata_info_uri,
                odata_version,
                is_published,
            ),
            expired_message="The saved SSO session expired while reading OData service information.",
        )
