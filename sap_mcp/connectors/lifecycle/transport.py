from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

from sap_mcp.connectors.core.base import BaseMixin
from sap_mcp.connectors.core.registry import ADT_BASE_PATH
from sap_mcp.errors import SapBackendError, ValidationError


class TransportsMixin(BaseMixin):
    async def transport_get(
        self,
        destination: str,
        development_package: str,
        object_name: str,
        object_type: str,
        is_creation: bool,
    ) -> dict[str, Any]:
        """Resolve a transport request number via the ADT Lock API.

        Uses the *standard ADT Lock API* (POST /sap/bc/adt/locks) — the
        community-standard approach used by Eclipse ADT, abap-adt-api,
        abapify/adt-cli, and vibing-steampunk.

        Falls back to E071/E070 table queries on Lock API failure (e.g.
        objects without valid source path, or OP system quirks).

        $TMP-package objects: Lock returns empty CORRNR — no transport needed.
        Task-locked objects: Lock returns the *parent* main request CORRNR.
        """
        self._assert_destination(destination)
        object_name = object_name.strip().upper()
        path_name = (await self._resolve_repository_object_name(object_type, object_name) or object_name).strip().upper()
        display_name = self._adt_object_name(object_type, path_name)

        if development_package.upper() == "$TMP":
            return self._transport_empty_result(display_name, need_transport=False)

        try:
            return await self._transport_via_lock(
                destination, development_package, path_name, display_name, object_type, is_creation
            )
        except SapBackendError:
            pass

        return await self._transport_via_se16(
            destination, development_package, display_name, object_type, is_creation
        )

    # ------------------------------------------------------------------
    # Primary path — ADT Lock API
    # ------------------------------------------------------------------

    async def _transport_via_lock(
        self,
        destination: str,
        development_package: str,
        path_name: str,
        display_name: str,
        object_type: str,
        is_creation: bool,
    ) -> dict[str, Any]:
        object_url = await self._build_object_url(object_type, path_name, is_creation)
        if not object_url:
            return await self._transport_via_se16(
                destination, development_package, display_name, object_type, is_creation
            )

        lock_result = await self.lock_object(object_url, is_creation=is_creation)

        # Lock API not available on this system → fall back to E071/E070
        if not lock_result.get("locked"):
            return await self._transport_via_se16(
                destination, development_package, display_name, object_type, is_creation
            )

        lock_handle = lock_result.get("lock_handle", "")
        corrnr = lock_result.get("corrnr", "")

        # Release lock immediately — we only needed the CORRNR
        if lock_handle:
            await self.unlock_object(lock_handle, object_url)

        if not corrnr:
            return self._transport_empty_result(display_name, need_transport=lock_result.get("needs_transport", True))

        return {
            "transportRequests": [{
                "number": corrnr,
                "text": "",
                "owner": lock_result.get("owner", ""),
                "target": "",
                "object_name": display_name,
            }],
            "informationMessages": [],
            "isRecordingRequired": False,
        }

    async def _build_object_url(self, object_type: str, obj_name: str, is_creation: bool) -> str:
        try:
            target = self._resolve_source_target(object_type, obj_name, "main", None, None)
            return target.uri
        except (AttributeError, ValueError, ValidationError):
            registration = self._find_path_registration(object_type)
            if registration:
                return self._object_path(registration.canonical_type, obj_name)
            return ""

    # ------------------------------------------------------------------
    # Fallback path — E071/E070 tables
    # ------------------------------------------------------------------

    async def _transport_via_se16(
        self,
        destination: str,
        development_package: str,
        obj_name: str,
        object_type: str,
        is_creation: bool,
    ) -> dict[str, Any]:
        """Fallback: resolve transport via E071/E070 table queries."""
        e071_sql = f"SELECT TRKORR, PGMID, OBJECT, OBJ_NAME, LOCKFLAG FROM E071 WHERE OBJ_NAME = '{obj_name}'"
        e071_rows = await self._freestyle_query(e071_sql)

        if not e071_rows:
            return self._transport_empty_result(obj_name)

        # Collect unique request numbers
        tr_numbers = sorted({r["TRKORR"] for r in e071_rows if r.get("TRKORR")})

        # Step 2: Query E070 for status of all found requests
        e070_map = await self._query_e070_statuses(tr_numbers)
        if not e070_map:
            return self._transport_empty_result(obj_name)

        # Step 3: Query E07T for descriptions
        e07t_texts = await self._query_e07t_texts(tr_numbers)

        # Step 4: Identify modifiable requests.
        #   Tasks (S/T) → can't be used for writes; use parent as "number"
        #   Main requests (K/W) → usable directly
        requests: list[dict[str, str]] = []
        for tr_number in tr_numbers:
            e070 = e070_map.get(tr_number)
            if not e070 or e070.get("TRSTATUS", "") != "D":
                continue  # Not modifiable — skip
            parent = e070.get("STRKORR", "").strip().upper()
            tr_function = e070.get("TRFUNCTION", "")
            is_task = tr_function in ("S", "T") and parent
            entry: dict[str, str] = {
                "number": parent if is_task else tr_number,
                "text": e07t_texts.get(tr_number, ""),
                "owner": e070.get("AS4USER", ""),
                "target": "",
                "function": tr_function,
                "object_name": obj_name,
            }
            if is_task:
                entry["task_number"] = tr_number
            requests.append(entry)

        # If no modifiable requests found, check if any released ones exist (informational)
        info_messages: list[dict[str, str]] = []
        if not requests:
            # Inform the user whether the object exists in released requests
            released = [r["TRKORR"] for r in e070_map.values() if r.get("TRSTATUS") == "R"]
            if released:
                info_messages.append({
                    "type": "Info",
                    "text": f"Object {obj_name} found in released (non-modifiable) request(s): {', '.join(released)}",
                })
            else:
                info_messages.append({
                    "type": "Info",
                    "text": f"No modifiable transport request found for {obj_name}",
                })

        return {
            "transportRequests": requests,
            "informationMessages": info_messages,
            "isRecordingRequired": not bool(requests),
        }

    async def _freestyle_query(self, sql: str, top: int = 200) -> list[dict[str, Any]]:
        """Execute a freestyle SQL query and return rows."""
        result = await self.data_preview("freestyle", sql, top=top)
        return result.get("rows", []) or []

    async def _query_e070_statuses(self, tr_numbers: list[str]) -> dict[str, dict[str, str]]:
        """Query E070 for request status and parent relationship."""
        if not tr_numbers:
            return {}
        in_clause = ", ".join(f"'{tr}'" for tr in tr_numbers)
        sql = f"SELECT TRKORR, TRFUNCTION, TRSTATUS, STRKORR, AS4USER, AS4DATE, AS4TIME FROM E070 WHERE TRKORR IN ({in_clause})"
        rows = await self._freestyle_query(sql)
        return {r["TRKORR"]: r for r in rows if r.get("TRKORR")}

    async def _query_e07t_texts(self, tr_numbers: list[str]) -> dict[str, str]:
        """Query E07T for transport request descriptions (language 1 = EN)."""
        if not tr_numbers:
            return {}
        in_clause = ", ".join(f"'{tr}'" for tr in tr_numbers)
        sql = f"SELECT TRKORR, AS4TEXT FROM E07T WHERE TRKORR IN ({in_clause}) AND LANGU = '1'"
        rows = await self._freestyle_query(sql, top=len(tr_numbers) * 2)
        return {r["TRKORR"]: r.get("AS4TEXT", "") for r in rows if r.get("TRKORR")}

    @staticmethod
    def _transport_empty_result(object_name: str = "", need_transport: bool = True) -> dict[str, Any]:
        msgs = []
        if object_name:
            msgs.append({
                "type": "Info",
                "text": f"$TMP package — no transport required" if not need_transport
                       else f"No transport request found for {object_name}",
            })
        return {
            "transportRequests": [],
            "informationMessages": msgs,
            "isRecordingRequired": need_transport,
        }

    async def transport_create(
        self,
        destination: str,
        development_package: str,
        transport_description: str,
        is_creation: bool = True,
        object_name: str | None = None,
        object_type: str | None = None,
        owner: str = "",
    ) -> dict[str, Any]:
        """Create a transport request via the official ADT CTS API.

        POST /sap/bc/adt/cts/transports
        Content-Type: application/vnd.sap.as+xml; charset=UTF-8;
                      dataname=com.sap.adt.CreateCorrectionRequest
        Accept: text/plain
        Body: abapXml { DEVCLASS, REQUEST_TEXT, REF, OPERATION }

        REF is the ADT object URI and OPERATION is "I" (Insert).
        """
        self._assert_destination(destination)
        package_name = development_package.upper()
        text = transport_description or f"Transport for {package_name}"

        if not object_name or not object_type:
            return {
                "transportRequestNumber": "", "number": "",
                "message": "Transport creation requires object_name and object_type to reference an object",
            }

        ref_uri = await self._build_object_url(object_type, object_name, is_creation)
        if not ref_uri:
            return {
                "transportRequestNumber": "", "number": "",
                "message": "Failed to build object URL for transport creation",
            }

        xml_body = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<asx:abap xmlns:asx="http://www.sap.com/abapxml" version="1.0">'
            "<asx:values>"
            "<DATA>"
            f"<DEVCLASS>{self._xml_escape(package_name)}</DEVCLASS>"
            f"<REQUEST_TEXT>{self._xml_escape(text)}</REQUEST_TEXT>"
            f"<REF>{self._xml_escape(ref_uri)}</REF>"
            "<OPERATION>I</OPERATION>"
            "</DATA>"
            "</asx:values></asx:abap>"
        )
        try:
            response = await self._request(
                "POST",
                f"{ADT_BASE_PATH}/cts/transports",
                content=xml_body.encode("utf-8"),
                headers={"Content-Type": "application/vnd.sap.as+xml; charset=UTF-8; dataname=com.sap.adt.CreateCorrectionRequest"},
                accept="text/plain",
            )
        except SapBackendError as error:
            details = error.details
            return {
                "transportRequestNumber": "", "number": "",
                "message": "Failed to create transport request",
                "error": str(error), "details": details,
            }
        request_number = (response.text or "").strip().rsplit("/", 1)[-1]
        return {
            "transportRequestNumber": request_number,
            "number": request_number,
            "message": f"Transport request {request_number} created",
            "status_code": response.status_code,
        }

    async def transport_list_tasks(self, transport_request_number: str) -> dict[str, Any]:
        """List tasks under a transport request.

        ADT: GET /sap/bc/adt/cts/transportrequests/{tr_number}/tasks
        """
        tr_number = transport_request_number.strip().upper()
        response = await self._request(
            "GET",
            f"{ADT_BASE_PATH}/cts/transportrequests/{quote(tr_number)}/tasks",
            accept="application/atom+xml, application/xml, */*",
        )
        tasks = self._parse_transport_collection(response.text, "task")
        return {
            "transportRequestNumber": tr_number,
            "tasks": tasks,
            "count": len(tasks),
            "status_code": response.status_code,
        }

    async def transport_list_objects(self, transport_request_number: str) -> dict[str, Any]:
        """List objects in a transport request.

        ADT: GET /sap/bc/adt/cts/transportrequests/{tr_number}/items
        """
        tr_number = transport_request_number.strip().upper()
        response = await self._request(
            "GET",
            f"{ADT_BASE_PATH}/cts/transportrequests/{quote(tr_number)}/items",
            accept="application/atom+xml, application/xml, */*",
        )
        items = self._parse_transport_collection(response.text, "item")
        return {
            "transportRequestNumber": tr_number,
            "items": items,
            "count": len(items),
            "status_code": response.status_code,
        }

    async def transport_release(self, transport_request_number: str) -> dict[str, Any]:
        """Release a transport request.

        ADT: POST /sap/bc/adt/cts/transportrequests/{tr_number}?action=release
        """
        tr_number = transport_request_number.strip().upper()
        response = await self._request(
            "POST",
            f"{ADT_BASE_PATH}/cts/transportrequests/{quote(tr_number)}",
            params={"action": "release"},
            accept="application/xml, */*",
        )
        return {
            "transportRequestNumber": tr_number,
            "released": response.status_code < 400,
            "message": f"Transport request {tr_number} released",
            "status_code": response.status_code,
        }

    def _parse_transport_collection(self, text: str, entry_kind: str) -> list[dict[str, Any]]:
        """Parse Atom feed for transport tasks or items."""
        if not text.strip():
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return [{"raw": text.strip()}]
        entries = []
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            item = {}
            title = entry.find("{http://www.w3.org/2005/Atom}title")
            if title is not None and title.text:
                item["title"] = title.text.strip()
            for child in entry:
                tag = child.tag.rsplit("}", 1)[-1]
                if tag == "category":
                    item.setdefault("category", child.attrib.get("term", ""))
                elif tag == "link":
                    item.setdefault("uri", child.attrib.get("href", ""))
                    item.setdefault("type", child.attrib.get("type", ""))
                elif child.text and child.text.strip():
                    item[tag] = child.text.strip()
            if item:
                item["kind"] = entry_kind
                entries.append(item)
        return entries
