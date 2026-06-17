from __future__ import annotations

from sap_mcp.connectors.official.base import OfficialBaseMixin


class DestinationsMixin(OfficialBaseMixin):
    async def list_destinations(self) -> list[str]:
        await self.discovery()
        return [self._destination_id()]
