from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from sap_mcp.connectors.core.registry import ADT_BASE_PATH
from sap_mcp.errors import SapBackendError, ValidationError


class AdtWhereUsedMixin:
    async def where_used(
        self,
        object_type: str,
        name: str,
        enable_all_types: bool = False,
    ) -> dict[str, Any]:
        """Find all usages of an ABAP object (Where-Used list).

        ADT: GET /sap/bc/adt/repository/whereused?objectName={name}&objectType={type}
        """
        resolved_name = await self._resolve_repository_object_name(object_type, name)
        object_name = (resolved_name or name).strip().upper()
        if not object_name:
            raise ValidationError("name is required")
        adt_object_type = self._adt_object_type(object_type)
        adt_object_name = self._adt_object_name(object_type, object_name)

        params: dict[str, str] = {
            "objectName": adt_object_name,
            "objectType": adt_object_type,
        }
        if enable_all_types:
            params["enableAllTypes"] = "true"

        try:
            response = await self._request(
                "GET",
                f"{ADT_BASE_PATH}/repository/whereused",
                params=params,
                accept="application/xml, application/*, */*",
            )
        except SapBackendError as error:
            if error.details.get("status_code") != 404:
                raise
            return await self._where_used_source_fallback(adt_object_type, adt_object_name, enable_all_types)

        references, total = self._parse_where_used(response.text)
        result = {
            "object_type": adt_object_type,
            "name": adt_object_name,
            "enable_all_types": enable_all_types,
            "references": references,
            "total_references": total,
            "status_code": response.status_code,
            "source": "adt_whereused",
        }
        if object_name != adt_object_name:
            result["resolved_name"] = object_name
        return result

    async def _where_used_source_fallback(
        self,
        object_type: str,
        object_name: str,
        enable_all_types: bool,
    ) -> dict[str, Any]:
        results = await self._search_repository_objects(
            f"*{object_name}*",
            100,
            None,
            None,
        )
        references = []
        for item in results:
            name = item.get("name")
            item_type = item.get("type")
            if not name or name.upper() == object_name:
                continue
            if item_type and item_type.upper().split("/", 1)[0] == object_type:
                continue
            references.append({
                "name": name,
                "type": item_type or "",
                "uri": item.get("uri", ""),
                "packageName": item.get("packageName"),
                "description": item.get("description", item.get("title", "")),
            })
        return {
            "object_type": object_type,
            "name": object_name,
            "enable_all_types": enable_all_types,
            "references": references,
            "total_references": len(references),
            "status_code": 200,
            "source": "repository_search_fallback",
            "fallback_reason": "ADT where-used endpoint returned 404",
        }

    def _parse_where_used(self, text: str) -> tuple[list[dict[str, Any]], int]:
        """Parse the Where-Used XML response.

        Expected structure (ADT Atom feed):
        <feed>
          <entry>
            <title>ZCL_MY_CLASS</title>
            <category term="CLAS/OC" />
            <link href="/sap/bc/adt/oo/classes/zcl_my_class" />
            <summary>description</summary>
          </entry>
          ...
        </feed>
        """
        if not text.strip():
            return [], 0

        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return [{"raw": text.strip()}], 0

        references: list[dict[str, Any]] = []
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            ref: dict[str, Any] = {}

            title = entry.find("{http://www.w3.org/2005/Atom}title")
            if title is not None and title.text:
                ref["name"] = title.text.strip()

            for child in entry:
                tag = child.tag.rsplit("}", 1)[-1]

                if tag == "category":
                    ref["type"] = child.attrib.get("term", "")
                elif tag == "link":
                    ref["uri"] = child.attrib.get("href", "")
                elif tag == "summary":
                    if child.text and child.text.strip():
                        ref["description"] = child.text.strip()
                elif tag == "published":
                    ref["published"] = child.text.strip() if child.text else None
                elif tag == "updated":
                    ref["updated"] = child.text.strip() if child.text else None
                else:
                    # Collect other watt metadata as generic fields
                    if child.text and child.text.strip():
                        ref.setdefault("extra", {})[tag] = child.text.strip()

            if ref:
                references.append(ref)

        total = len(references)
        # Try to find totalResults from OpenSearch namespace
        for element in root.iter("{http://a9.com/-/spec/opensearch/1.1/}totalResults"):
            if element.text:
                try:
                    total = int(element.text)
                except ValueError:
                    pass

        return references, total
