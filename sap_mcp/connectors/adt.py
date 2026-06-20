from __future__ import annotations

from typing import Any

from sap_mcp.auth.browser_sso import BrowserSession
from sap_mcp.config import AbapDevConfig
from sap_mcp.connectors.core.constants import ADT_SESSION_STATELESS
from sap_mcp.connectors.core.http import AdtHttpMixin
from sap_mcp.connectors.core.xml_utils import AdtXmlMixin
from sap_mcp.connectors.core.paths import AdtPathMixin
from sap_mcp.connectors.core.authorization import AdtAuthorizationMixin
from sap_mcp.connectors.core.base import BaseMixin
from sap_mcp.connectors.core.registry import ADT_ACCEPT, ADT_BASE_PATH
from sap_mcp.connectors.objects.search import AdtSearchMixin
from sap_mcp.connectors.objects.signature import AdtSignatureMixin
from sap_mcp.connectors.objects.creation import AdtCreationMixin, CreationMixin
from sap_mcp.connectors.objects.source import AdtSourceMixin
from sap_mcp.connectors.objects.data_preview import DataPreviewMixin
from sap_mcp.connectors.objects.execution import ExecutionMixin
from sap_mcp.connectors.objects.function_module import FunctionModuleMixin
from sap_mcp.connectors.objects.delete import AdtDeleteMixin
from sap_mcp.connectors.objects.metadata import AdtMetadataMixin
from sap_mcp.connectors.objects.where_used import AdtWhereUsedMixin
from sap_mcp.connectors.lifecycle.activation import AdtActivationMixin
from sap_mcp.connectors.lifecycle.quality import AdtQualityMixin
from sap_mcp.connectors.lifecycle.syntax_check import AdtSyntaxCheckMixin
from sap_mcp.connectors.lifecycle.transport import TransportsMixin
from sap_mcp.connectors.lifecycle.lock import AdtLockMixin
from sap_mcp.connectors.integration.service_binding import AdtServiceBindingMixin
from sap_mcp.connectors.analysis.cds_analysis import CdsAnalysisMixin
from sap_mcp.connectors.analysis.code_assist import CodeAssistMixin
from sap_mcp.connectors.integration.business_services import BusinessServicesMixin
from sap_mcp.connectors.integration.generators import GeneratorsMixin
from sap_mcp.connectors.integration.destinations import DestinationsMixin
from sap_mcp.connectors.system.info import SystemInfoMixin


ADT_CONNECTOR_MIXIN_CONTRACTS = {
    "BaseMixin": ("_assert_destination", "_creatable_type", "_coerce_adt_path"),
    "DataPreviewMixin": ("_request",),
    "CdsAnalysisMixin": ("_request",),
    "CodeAssistMixin": ("_request",),
    "ExecutionMixin": ("_request",),
    "FunctionModuleMixin": ("activate_object", "create_object", "data_preview", "delete_object", "execute"),
    "SystemInfoMixin": ("_request",),
    "AdtLockMixin": ("_request",),
    "AdtActivationMixin": (
        "_adt_object_name", "_adt_object_type", "_assert_object_write_allowed", "_object_path",
        "_object_references_xml", "_request", "_resolve_repository_object_name",
    ),
    "AdtAuthorizationMixin": (
        "_find_path_registration", "_function_module_parts", "_match_registration_name", "_search_repository_objects",
    ),
    "AdtCreationMixin": (
        "_assert_object_write_allowed", "_assert_package_allowed", "_assert_write_allowed",
        "_collection_path", "_container_ref_xml", "_dictionary_blue_xml",
        "_function_module_parts", "_initial_create_source",
        "_normalize_odata_version", "_normalized_etag",
        "_path_registration", "_repository_metadata_xml",
        "_request", "_source_path", "_xml_escape", "object_exists",
    ),
    "AdtDeleteMixin": (
        "_assert_object_write_allowed", "_assert_write_allowed",
        "_canonical_object_type", "_find_path_registration",
        "_if_match_etag", "_normalized_etag", "_object_path",
        "_request", "_resolve_repository_object_name", "_server_etag_from_precondition",
        "_source_etag", "_source_path", "_xml_local_name",
    ),
    "AdtHttpMixin": ("_clean_xml_name",),
    "AdtMetadataMixin": (
        "_adt_relative_url", "_clean_xml_name",
        "_find_path_registration", "_normalize_include_type",
    ),
    "AdtWhereUsedMixin": ("_adt_object_name", "_adt_object_type", "_request", "_resolve_repository_object_name", "_search_repository_objects"),
    "AdtPathMixin": ("_default_source",),
    "AdtQualityMixin": (
        "_adt_api_path", "_assert_package_read_allowed",
        "_clean_xml_name", "_request", "_xml_escape",
    ),
    "AdtSyntaxCheckMixin": ("_adt_object_name", "_adt_object_type", "_request", "_resolve_repository_object_name"),
    "TransportsMixin": (
        "_adt_object_name", "_assert_destination", "_find_path_registration", "_object_path",
        "_request", "_resolve_repository_object_name", "_resolve_source_target",
        "data_preview", "lock_object", "unlock_object",
    ),
    "AdtSearchMixin": (
        "_assert_package_read_allowed", "_clean_xml_name",
        "_function_module_parts", "_is_package_write_allowed",
        "_is_source_search_type", "_path_registration",
        "_request", "read_source",
    ),
    "AdtSignatureMixin": (
        "_canonical_type", "function_metadata", "read_source",
    ),
    "AdtServiceBindingMixin": (
        "_assert_object_write_allowed", "_assert_write_allowed",
        "_object_references_xml", "_parse_status_messages",
        "_request", "_xml_local_name", "read_source",
    ),
    "AdtSourceMixin": (
        "_adt_relative_url", "_assert_object_write_allowed",
        "_assert_write_allowed", "_augment_update_error",
        "_build_read_hint", "_is_metadata_write_path",
        "_is_oo_source_type", "_normalized_etag",
        "_oo_source_part", "_request",
        "_resolve_repository_object_name", "_resolve_source_target", "_server_etag_from_precondition",
    ),
}


def _validate_mixin_contracts(connector_type: type, contracts: dict[str, tuple[str, ...]]) -> None:
    missing = {
        mixin_name: tuple(method_name for method_name in method_names if not hasattr(connector_type, method_name))
        for mixin_name, method_names in contracts.items()
    }
    missing = {mixin_name: method_names for mixin_name, method_names in missing.items() if method_names}
    if missing:
        details = "; ".join(f"{mixin_name}: {', '.join(method_names)}" for mixin_name, method_names in missing.items())
        raise TypeError(f"AdtConnector mixin contracts are incomplete: {details}")


class AdtConnector(
    # core infrastructure (BaseMixin inherited via CreationMixin, TransportsMixin, etc.)
    AdtHttpMixin,
    AdtXmlMixin,
    AdtPathMixin,
    AdtAuthorizationMixin,
    # object CRUD
    AdtCreationMixin,
    CreationMixin,
    AdtSearchMixin,
    AdtSignatureMixin,
    AdtSourceMixin,
    DataPreviewMixin,
    ExecutionMixin,
    FunctionModuleMixin,
    AdtDeleteMixin,
    AdtMetadataMixin,
    AdtWhereUsedMixin,
    # lifecycle
    AdtActivationMixin,
    AdtQualityMixin,
    AdtSyntaxCheckMixin,
    TransportsMixin,
    AdtLockMixin,
    # integration
    CdsAnalysisMixin,
    CodeAssistMixin,
    AdtServiceBindingMixin,
    BusinessServicesMixin,
    GeneratorsMixin,
    DestinationsMixin,
    # system
    SystemInfoMixin,
):
    def __init__(self, config: AbapDevConfig, session: BrowserSession):
        self.config = config
        self.session = session
        self._set_adt_session_type(ADT_SESSION_STATELESS)

    async def discovery(self) -> dict[str, Any]:
        response = await self._request("GET", f"{ADT_BASE_PATH}/discovery", accept=ADT_ACCEPT)
        self._persist_session_cookies()
        return {
            "connected": True,
            "status_code": response.status_code,
            "content_type": response.content_type,
            "system_url": self.session.system_url,
        }

    async def get_object_metadata(
        self,
        object_type: str | None = None,
        name: str | None = None,
        uri: str | None = None,
    ) -> dict[str, Any]:
        name = await self._resolve_repository_object_name(object_type, name) if object_type and name and not uri else name
        path = self._metadata_path(object_type, name, uri)
        response = await self._request("GET", path, accept="application/xml, application/*, */*")
        requested_type = object_type.upper() if object_type else None
        requested_name = name.upper() if name else None
        return self._parse_object_metadata(
            response.text, path,
            self._normalized_etag(response.headers.get("etag"), response.content_type),
            response.content_type, response.status_code,
            requested_type, requested_name,
        )


_validate_mixin_contracts(AdtConnector, ADT_CONNECTOR_MIXIN_CONTRACTS)
