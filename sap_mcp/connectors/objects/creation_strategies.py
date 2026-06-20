"""Creation strategy framework for ABAP ADT objects.

Each ABAP repository object type has a specific ADT creation protocol.
This module provides a strategy-based approach where each type maps to a strategy
that implements the correct creation workflow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from sap_mcp.connectors.adt import AdtConnector
    from sap_mcp.connectors.core.registry import AdtPathRegistration

_VERIFIED_METADATA_THEN_SOURCE: Final[frozenset[str]] = frozenset({"DDLS", "DCLS", "DDLX", "CLAS", "INTF", "SRVD", "PROG"})
_VERIFIED_METADATA_ONLY: Final[frozenset[str]] = frozenset({"FUGR", "DTEL", "DOMA", "DEVC"})
_VERIFIED_PUT_SOURCE: Final[frozenset[str]] = frozenset()
_VERIFIED_BLUE_SOURCE: Final[frozenset[str]] = frozenset({"BDEF", "TABL"})


class CreationStrategy(ABC):
    @abstractmethod
    async def create(
        self, connector: AdtConnector, registration: AdtPathRegistration,
        name: str, package: str, description: str, source: str, reason: str, **kwargs: Any,
    ) -> dict[str, Any]:
        ...


async def _put_created_source(
    connector: AdtConnector, registration: AdtPathRegistration,
    name: str, package: str, description: str, source: str, create_response: dict[str, Any],
    transport_request_number: str | None = None,
) -> dict[str, Any]:
    from sap_mcp.errors import SapBackendError
    try:
        result = await connector._lock_put_unlock_source(
            registration.canonical_type, name, package, description, source, transport_request_number,
        )
        return {**create_response, **result}
    except SapBackendError as error:
        source_path = connector._source_path(registration.canonical_type, name)
        return await connector._created_with_pending_source(
            registration.canonical_type, name.upper(), package, create_response, source_path, error)


class PutSourceStrategy(CreationStrategy):
    async def create(
        self, connector: AdtConnector, registration: AdtPathRegistration,
        name: str, package: str, description: str, source: str, reason: str, **kwargs: Any,
    ) -> dict[str, Any]:
        path = connector._source_path(registration.canonical_type, name)
        response = await connector._request(
            "PUT", path, content=source.encode("utf-8"),
            headers={
                "If-None-Match": "*", "Content-Type": "text/plain; charset=utf-8",
                "X-SAP-ADT-Package": package.upper(), "X-SAP-ADT-Description": description,
            }, accept="application/xml, text/plain, */*",
        )
        return connector._created_result(registration.canonical_type, name, package, response)


class MetadataOnlyStrategy(CreationStrategy):
    async def create(
        self, connector: AdtConnector, registration: AdtPathRegistration,
        name: str, package: str, description: str, source: str, reason: str, **kwargs: Any,
    ) -> dict[str, Any]:
        if registration.canonical_type == "DEVC":
            return await connector._create_package(registration, name, package, description)
        if registration.canonical_type == "DTEL":
            return await connector._create_data_element(registration, name, package, description)
        if registration.canonical_type == "DOMA":
            return await connector._create_domain(registration, name, package, description)
        return await connector._create_metadata_object(registration, name, package, description, kwargs.get("transport_request_number"))


class MetadataThenSourceStrategy(CreationStrategy):
    async def create(
        self, connector: AdtConnector, registration: AdtPathRegistration,
        name: str, package: str, description: str, source: str, reason: str, **kwargs: Any,
    ) -> dict[str, Any]:
        transport_request_number = kwargs.get("transport_request_number")
        try:
            create_response = await connector._create_metadata_object(registration, name, package, description, transport_request_number)
        except Exception as error:
            from sap_mcp.errors import SapBackendError
            if not isinstance(error, SapBackendError):
                raise
            exists = await connector.object_exists(registration.canonical_type, name)
            if not exists["exists"]:
                raise
            create_response = connector._created_result(
                registration.canonical_type,
                name,
                package,
                response=type("PendingCreateResponse", (), {"headers": {}, "content_type": "", "status_code": error.details.get("status_code", 500)})(),
            )
            source_path = connector._source_path(registration.canonical_type, name)
            return await connector._created_with_pending_source(registration.canonical_type, name.upper(), package, create_response, source_path, error)
        if not source.strip():
            return create_response
        return await _put_created_source(connector, registration, name, package, description, source, create_response, transport_request_number)


class UnknownProtocolStrategy(CreationStrategy):
    def __init__(self, reason: str = "creation protocol not verified"):
        self._reason = reason

    async def create(
        self, connector: AdtConnector, registration: AdtPathRegistration,
        name: str, package: str, description: str, source: str, reason: str, **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "created": False, "object_type": registration.canonical_type, "name": name.upper(),
            "error": (
                f"Cannot create {registration.canonical_type} '{name}': {self._reason}. "
                "The ADT creation protocol for this object type is not known. "
                "Creation in Eclipse ADT likely uses a custom protocol not available "
                "through the standard ADT REST API."
            ),
            "details": {"hint": "Try creating the object in Eclipse ADT to capture the protocol", "known_support": False},
        }


class BlueSourceRAPStrategy(CreationStrategy):
    async def create(
        self, connector: AdtConnector, registration: AdtPathRegistration,
        name: str, package: str, description: str, source: str, reason: str, **kwargs: Any,
    ) -> dict[str, Any]:
        from sap_mcp.errors import SapBackendError
        object_name = name.upper()
        implementation_type = kwargs.get("implementation_type", "Managed")
        transport_request = kwargs.get("transport_request_number", "")
        language = "EN"
        adt_type = getattr(registration, 'create_adt_type', None) or f"{registration.canonical_type}/DT"
        template_xml = ""
        if registration.canonical_type == "BDEF":
            template_xml = (
                "<adtcore:adtTemplate>"
                f'<adtcore:adtProperty adtcore:key="implementation_type">{implementation_type}</adtcore:adtProperty>'
                "</adtcore:adtTemplate>"
            )
        xml_body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<blue:blueSource xmlns:blue="http://www.sap.com/wbobj/blue" '
            'xmlns:adtcore="http://www.sap.com/adt/core" '
            f'adtcore:name="{object_name}" adtcore:type="{adt_type}" '
            f'adtcore:description="{connector._xml_escape(description[:60])}" '
            f'adtcore:language="{language}" adtcore:masterLanguage="{language}">'
            f"{template_xml}"
            f"{connector._package_ref_xml(package)}"
            "</blue:blueSource>"
        )
        params: dict[str, str] = {}
        if transport_request:
            params["corrNr"] = transport_request
        collection_url = connector._collection_path(registration.canonical_type)
        try:
            response = await connector._request(
                "POST", collection_url, params=params or None, content=xml_body.encode("utf-8"),
                headers={"Content-Type": "application/vnd.sap.adt.blues.v1+xml; charset=utf-8"},
                accept="application/vnd.sap.adt.blues.v1+xml, application/xml, */*",
            )
        except SapBackendError as error:
            return {"created": False, "object_type": registration.canonical_type, "name": object_name, "error": str(error), "details": error.details}
        if not source.strip():
            return connector._created_result(registration.canonical_type, object_name, package, response, source_written=False)
        create_response = connector._created_result(registration.canonical_type, object_name, package, response, source_written=False)
        return await _put_created_source(connector, registration, name, package, description, source, create_response)


class FunctionModuleStrategy(CreationStrategy):
    async def create(
        self, connector: AdtConnector, registration: AdtPathRegistration,
        name: str, package: str, description: str, source: str, reason: str, **kwargs: Any,
    ) -> dict[str, Any]:
        return await connector._create_function_module(registration, name, package, description, source)


class ServiceBindingStrategy(CreationStrategy):
    async def create(
        self, connector: AdtConnector, registration: AdtPathRegistration,
        name: str, package: str, description: str, source: str, reason: str, **kwargs: Any,
    ) -> dict[str, Any]:
        service_binding_version = kwargs.get("service_binding_version")
        return await connector._create_srvb(registration, name, package, description, source, service_binding_version)


class CreationStrategyRegistry:
    def __init__(self):
        self._strategies: dict[str, CreationStrategy] = {}
        self._register_verified()

    def _register_verified(self) -> None:
        put_source = PutSourceStrategy()
        metadata_only = MetadataOnlyStrategy()
        metadata_then_source = MetadataThenSourceStrategy()
        blue_source = BlueSourceRAPStrategy()
        func_strategy = FunctionModuleStrategy()
        srvb_strategy = ServiceBindingStrategy()
        for t in _VERIFIED_PUT_SOURCE:
            self._strategies[t] = put_source
        for t in _VERIFIED_METADATA_ONLY:
            self._strategies[t] = metadata_only
        for t in _VERIFIED_METADATA_THEN_SOURCE:
            self._strategies[t] = metadata_then_source
        for t in _VERIFIED_BLUE_SOURCE:
            self._strategies[t] = blue_source
        self._strategies["FUNC"] = func_strategy
        self._strategies["SRVB"] = srvb_strategy

    def register(self, canonical_type: str, strategy: CreationStrategy) -> None:
        self._strategies[canonical_type] = strategy

    def get(self, canonical_type: str) -> CreationStrategy | None:
        return self._strategies.get(canonical_type)

    def has(self, canonical_type: str) -> bool:
        return canonical_type in self._strategies


STRATEGY_REGISTRY: Final[CreationStrategyRegistry] = CreationStrategyRegistry()
