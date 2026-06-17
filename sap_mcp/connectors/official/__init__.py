from __future__ import annotations

from sap_mcp.connectors.official.activation import OfficialActivationMixin
from sap_mcp.connectors.official.business_services import BusinessServicesMixin
from sap_mcp.connectors.official.creation import CreationMixin
from sap_mcp.connectors.official.destinations import DestinationsMixin
from sap_mcp.connectors.official.generators import GeneratorsMixin
from sap_mcp.connectors.official.transports import TransportsMixin


class AdtOfficialCompatibilityMixin(
    DestinationsMixin,
    CreationMixin,
    GeneratorsMixin,
    TransportsMixin,
    BusinessServicesMixin,
    OfficialActivationMixin,
):
    """ADT MCP-compatible tool surface, split by ABAP workflow domain."""
