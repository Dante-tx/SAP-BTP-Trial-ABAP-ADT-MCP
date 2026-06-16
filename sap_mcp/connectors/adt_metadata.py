from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from sap_mcp.errors import ValidationError


class AdtMetadataMixin:
    def _parse_object_metadata(
        self,
        text: str,
        path: str,
        etag: str | None,
        content_type: str,
        status_code: int,
        requested_type: str | None,
        requested_name: str | None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "uri": path,
            "object_type": requested_type,
            "type": requested_type,
            "name": requested_name,
            "package": None,
            "description": None,
            "etag": etag,
            "content_type": content_type,
            "status_code": status_code,
            "links": [],
            "source_parts": [],
        }
        if not text.strip():
            return result
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            result["parse_error"] = True
            result["raw_excerpt"] = text[:500]
            return result

        root_attributes = self._clean_attributes(root.attrib)
        result["attributes"] = root_attributes
        result["name"] = root_attributes.get("name") or requested_name
        result["type"] = root_attributes.get("type") or requested_type
        result["object_type"] = self._metadata_object_type(result["type"], requested_type)
        result["description"] = root_attributes.get("description")
        result["package"] = self._metadata_package(root)
        result["links"] = self._metadata_links(root, path)
        result["source_parts"] = self._metadata_source_parts(root, path)
        return result

    def _metadata_object_type(self, adt_type: Any, requested_type: str | None) -> str | None:
        if requested_type:
            registration = self._find_path_registration(requested_type)
            return registration.canonical_type if registration else requested_type
        if isinstance(adt_type, str) and adt_type:
            return adt_type.split("/", 1)[0]
        return None

    def _metadata_package(self, root: ET.Element) -> str | None:
        package = self._clean_attributes(root.attrib).get("packageName")
        if package:
            return package
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag != "packageRef":
                continue
            attributes = self._clean_attributes(element.attrib)
            return attributes.get("name") or attributes.get("packageName")
        return None

    def _metadata_links(self, root: ET.Element, base_path: str) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        base = f"{base_path.rstrip('/')}/"
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "link":
                continue
            item = self._clean_attributes(element.attrib)
            href = item.get("href")
            if href:
                item["href"] = self._adt_relative_url(base, href)
            links.append(item)
        return links

    def _metadata_source_parts(self, root: ET.Element, base_path: str) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_part(include_type: str, link_attributes: dict[str, str]) -> None:
            href = link_attributes.get("href")
            if not href:
                return
            uri = self._adt_relative_url(f"{base_path.rstrip('/')}/", href)
            if uri in seen:
                return
            seen.add(uri)
            etag = link_attributes.get("etag")
            parts.append(
                {
                    "include_type": include_type,
                    "uri": uri,
                    "etag": etag,
                    "content_type": link_attributes.get("type"),
                    "source_kind": "source",
                    "round_trippable": True,
                    "writable_uri": uri,
                    "writable_etag": etag,
                }
            )

        for element in root.iter():
            attributes = self._clean_attributes(element.attrib)
            include_type = attributes.get("includeType")
            if not include_type:
                continue
            try:
                normalized_include = self._normalize_include_type(include_type)
            except ValidationError:
                normalized_include = include_type.strip().lower()
            for link in element.findall("{http://www.w3.org/2005/Atom}link"):
                link_attributes = self._clean_attributes(link.attrib)
                if self._metadata_link_is_source(link_attributes):
                    add_part(normalized_include, link_attributes)

        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "link":
                continue
            link_attributes = self._clean_attributes(element.attrib)
            if not self._metadata_link_is_source(link_attributes):
                continue
            href = link_attributes.get("href", "")
            include_type = self._include_type_from_href(href) or "main"
            add_part(include_type, link_attributes)

        order = {"main": 0, "definitions": 1, "implementations": 2, "macros": 3, "testclasses": 4}
        return sorted(parts, key=lambda item: order.get(item["include_type"], 99))

    def _metadata_link_is_source(self, attributes: dict[str, str]) -> bool:
        href = attributes.get("href", "")
        if not href or "?" in href or "#" in href:
            return False
        href_path = href.rstrip("/")
        if href_path == "source/main" or href_path.endswith("/source/main"):
            return True
        return self._include_type_from_href(href_path) is not None

    def _include_type_from_href(self, href: str) -> str | None:
        match = re.search(r"(?:^|/)includes/(?P<include>definitions|implementations|macros|testclasses)(?:$|[?#])", href)
        if match:
            return self._normalize_include_type(match.group("include"))
        return None

    def _clean_attributes(self, attributes: dict[str, str]) -> dict[str, str]:
        return {self._clean_xml_name(key): value for key, value in attributes.items()}
