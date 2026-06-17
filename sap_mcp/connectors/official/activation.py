from __future__ import annotations

from sap_mcp.connectors.official.base import OfficialBaseMixin


class OfficialActivationMixin(OfficialBaseMixin):
    def official_uri_objects(self, uris: list[str]) -> list[dict[str, str]]:
        return [self._object_ref_from_any_uri(uri) for uri in uris]
