from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

from sap_mcp.connectors.official.base import OfficialBaseMixin
from sap_mcp.errors import SapBackendError, ValidationError


class TransportsMixin(OfficialBaseMixin):
    async def transport_get(
        self,
        destination: str,
        object_name: str,
        object_type: str,
        development_package: str,
        is_creation: bool,
    ) -> dict[str, Any]:
        self._assert_destination(destination)
        uri = self._transport_ref_uri(object_type, object_name, development_package)
        body = self._asx_body({"DEVCLASS": development_package, "OPERATION": "I" if is_creation else "U", "URI": uri})
        try:
            response = await self._request(
                "POST",
                "/sap/bc/adt/cts/transportchecks",
                content=body.encode("utf-8"),
                headers={
                    "Accept": "application/vnd.sap.as+xml;charset=UTF-8;dataname=com.sap.adt.transport.service.checkData, application/xml, */*",
                    "Content-Type": "application/vnd.sap.as+xml; charset=UTF-8; dataname=com.sap.adt.transport.service.checkData",
                },
            )
        except SapBackendError as error:
            return {
                "transportRequests": [],
                "informationMessages": [str(error)],
                "isRecordingRequired": development_package.upper() != "$TMP",
                "error": str(error),
            }
        return self._parse_transport_check(response.text, development_package)

    async def transport_create(
        self,
        destination: str,
        development_package: str,
        transport_description: str,
        is_creation: bool,
        object_name: str | None = None,
        object_type: str | None = None,
    ) -> dict[str, Any]:
        self._assert_destination(destination)
        self._assert_write_allowed("Create transport request through ADT-compatible transport workflow")
        if development_package.upper() == "$TMP":
            return {"transportRequestNumber": "", "message": "Local package $TMP does not require a transport request"}
        self._assert_package_allowed(development_package)
        if not transport_description.strip():
            raise ValidationError("transportDescription is required")
        ref = self._transport_ref_uri(object_type or "DEVC/K", object_name or development_package, development_package)
        body = self._asx_body(
            {
                "DEVCLASS": development_package,
                "REQUEST_TEXT": transport_description[:60],
                "REF": ref,
                "OPERATION": "I" if is_creation else "U",
            }
        )
        response = await self._request(
            "POST",
            "/sap/bc/adt/cts/transports",
            content=body.encode("utf-8"),
            headers={
                "Accept": "text/plain, application/xml, */*",
                "Content-Type": "application/vnd.sap.as+xml; charset=UTF-8; dataname=com.sap.adt.CreateCorrectionRequest",
            },
        )
        transport_number = (response.text or "").strip().rstrip("/").rsplit("/", 1)[-1]
        return {"transportRequestNumber": transport_number, "message": "Transport request created"}

    def _transport_ref_uri(self, object_type: str, object_name: str, package_name: str) -> str:
        if object_type.upper() == "DEVC/K":
            return f"/sap/bc/adt/packages/{quote((object_name or package_name).lower())}"
        try:
            return self._object_path(object_type, object_name)
        except Exception:
            return f"/sap/bc/adt/repository/informationsystem/search?query={quote(object_name)}"

    def _parse_transport_check(self, text: str, package_name: str) -> dict[str, Any]:
        root = ET.fromstring(text)
        transport_requests = []
        information_messages = []
        recording_required = package_name.upper() != "$TMP"
        for element in root.iter():
            tag = self._xml_local_name(element.tag)
            if tag == "REQ_HEADER":
                header = self._direct_child_texts(element)
                number = header.get("TRKORR")
                if number:
                    transport_requests.append(
                        {
                            "transportRequestNumber": number,
                            "shortDescription": header.get("AS4TEXT", ""),
                            "owner": header.get("AS4USER", ""),
                        }
                    )
            elif tag == "CTS_MESSAGE":
                message = self._direct_child_texts(element)
                text_value = message.get("TEXT") or message.get("SHORT_TEXT")
                if text_value:
                    information_messages.append(text_value)
            elif tag == "RECORDING":
                recording_required = (element.text or "").strip().upper() not in {"", "N", "FALSE"}
        return {
            "transportRequests": transport_requests,
            "informationMessages": information_messages,
            "isRecordingRequired": recording_required,
        }
