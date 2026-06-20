"""ADT Lock/Unlock API — standard SAP ADT REST pattern for object locking.

Implements the *ADT Lock API* used by Eclipse ADT, abap-adt-api, abapify, and
vibing-steampunk — the community-standard approach for transport management.

Flow:
  1. POST /sap/bc/adt/locks → returns LOCK_HANDLE + CORRNR
  2. Write with ?corrNr=CORRNR
  3. DELETE /sap/bc/adt/locks?lockHandle=... → release
"""

from __future__ import annotations

import re
from typing import Any

from sap_mcp.connectors.core.base import BaseMixin
from sap_mcp.errors import SapBackendError


_LOCK_HANDLE_RE = re.compile(
    r'(?:LOCK_HANDLE|lh|lockHandle)\s*=\s*["\']?([^\s"\'&]+)',
    re.IGNORECASE,
)

ADT_LOCKS_PATH = "/sap/bc/adt/locks"
_ADT_CORE_NS = "http://www.sap.com/adt/core"


class AdtLockMixin(BaseMixin):
    """Mixin that provides ADT Lock/Unlock operations.

    Conforms to the same pattern used by Eclipse ADT, abap-adt-api, and
    abapify/adt-cli — the standard community approach.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def lock_object(
        self,
        object_url: str,
        *,
        is_creation: bool = False,
    ) -> dict[str, Any]:
        """Lock an ABAP object via the ADT Lock API.

        Returns a dict with ``corrnr`` (transport request number) and
        ``lock_handle`` (opaque handle for unlock).

        For $TMP-package objects the lock succeeds but ``corrnr`` is empty —
        no transport request is needed for writes.
        """
        body = self._lock_request_xml(object_url, is_creation=is_creation)
        try:
            response = await self._request(
                "POST",
                ADT_LOCKS_PATH,
                content=body.encode("utf-8"),
                headers={"Content-Type": "application/vnd.sap.as+xml;charset=UTF-8"},
                accept="application/vnd.sap.as+xml, application/xml, */*",
            )
        except SapBackendError as error:
            return {
                "locked": False,
                "lock_handle": "",
                "corrnr": "",
                "owner": "",
                "needs_transport": True,
                "error": str(error),
                "error_status": error.details.get("status_code", 0),
                "object_url": object_url,
            }

        return self._parse_lock_response(response.text, object_url)

    async def unlock_object(self, lock_handle: str, object_url: str) -> None:
        """Release a previously-held ADT lock."""
        body = self._lock_request_xml(object_url)
        try:
            await self._request(
                "DELETE",
                ADT_LOCKS_PATH,
                params={"lockHandle": lock_handle},
                content=body.encode("utf-8"),
                headers={
                    "Content-Type": "application/vnd.sap.as+xml;charset=UTF-8",
                },
                accept="application/xml, */*",
            )
        except SapBackendError:
            # Unlock failures are non-fatal — the lock session may already
            # be expired or the object was implicitly unlocked.
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _lock_request_xml(object_url: str, *, is_creation: bool = False) -> str:
        """Build the ADT lock request payload."""
        handle_attr = f' adtcore:handle="{ADT_LOCKS_PATH}"' if is_creation else ""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<adtcore:objectReferences xmlns:adtcore="{_ADT_CORE_NS}">'
            f'<adtcore:objectReference'
            f' adtcore:uri="{AdtLockMixin._xml_escape_attr(object_url)}"{handle_attr}/>'
            "</adtcore:objectReferences>"
        )

    @staticmethod
    def _parse_lock_response(xml_text: str, object_url: str) -> dict[str, Any]:
        """Extract LOCK_HANDLE and CORRNR from the ADT lock response."""
        # The response is a compact XML — use regex for robustness against
        # varying namespace prefixes and attribute ordering.
        pattern = re.compile(
            r'adtcore:uri\s*=\s*"([^"]*)"'
            r'.*?'
            r'(?:adtcore:lockHandle|adtcore:LOCK_HANDLE)\s*=\s*"([^"]*)"',
            re.DOTALL,
        )
        m = pattern.search(xml_text)
        if not m:
            # Try the simple variant
            handle = _LOCK_HANDLE_RE.search(xml_text)
            if not handle:
                return {
                    "locked": False,
                    "lock_handle": "",
                    "corrnr": "",
                    "owner": "",
                    "needs_transport": True,
                    "error": f"Lock response does not contain a lock handle: {xml_text[:200]}",
                    "error_status": 500,
                    "object_url": object_url,
                }
            lock_handle = handle.group(1)
        else:
            lock_handle = m.group(2)

        # Extract CORRNR (transport request number)
        corrnr = ""
        corrnr_m = re.search(
            r'(?:adtcore:corrNr|adtcore:CORRNR|corrNr)\s*=\s*"([^"]*)"',
            xml_text,
            re.IGNORECASE,
        )
        if corrnr_m:
            corrnr = corrnr_m.group(1).strip().upper()

        # Extract OWNER
        owner = ""
        owner_m = re.search(
            r'(?:adtcore:owner|adtcore:OWNER)\s*=\s*"([^"]*)"',
            xml_text,
            re.IGNORECASE,
        )
        if owner_m:
            owner = owner_m.group(1).strip().upper()

        return {
            "locked": True,
            "object_url": object_url,
            "lock_handle": lock_handle,
            "corrnr": corrnr,
            "owner": owner,
            "needs_transport": bool(corrnr),
        }

    @staticmethod
    def _xml_escape_attr(value: str) -> str:
        """Minimal XML attribute escape."""
        return (
            value.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
