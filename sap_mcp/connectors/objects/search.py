from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

from sap_mcp.connectors.core.registry import (
    ADT_BASE_PATH,
    DEFAULT_MAX_RESULTS,
    DEFAULT_PACKAGE_LIST_LIMIT,
    LARGE_PACKAGE_THRESHOLD,
    MAX_SEARCH_RESULTS_CAP,
    SUPPORTED_SEARCH_TYPES_HELP,
    SUPPORTED_TYPES_HELP,
)
from sap_mcp.errors import ValidationError


class AdtSearchMixin:
    async def search_objects(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        object_type: str | None = None,
        package: str | None = None,
        search_mode: str = "exact",
        sort_by: str | None = None,
    ) -> list[dict[str, Any]]:
        if package:
            self._assert_package_read_allowed(package)
        normalized_mode = search_mode.strip().lower()

        # Convert query for partial mode: ensure wildcard suffix
        search_query = query
        if normalized_mode == "partial":
            q = query.strip()
            if q and q != "*" and not q.endswith("*"):
                search_query = f"*{q}*" if not q.startswith("*") else f"{q}*"
        elif normalized_mode == "description":
            # ADT search doesn't have a native description-only mode;
            # broaden the query and let client-side filter on description
            q = query.strip()
            search_query = f"*{q}*" if q != "*" else q

        search_type = self._repository_search_type(object_type)
        results = await self._search_repository_objects(search_query, max_results, search_type, package)
        results = self._filter_repository_objects(results, object_type)

        # Filter by description if search_mode == "description"
        if normalized_mode == "description":
            needle = query.strip().casefold()
            results = [
                r for r in results
                if needle in (r.get("description") or "").casefold()
                or needle in (r.get("name") or "").casefold()
                or needle in self._description_words(r.get("description") or "")
            ]
            results = results[:max_results]

        # Sort if requested
        if sort_by:
            sort_key = sort_by.strip().lower()
            results = self._sort_search_results(results, sort_key)

        if results or not package or search_query.strip() in {"", "*"}:
            return results
        if object_type and not self._is_source_search_type(object_type):
            return results
        if not self._is_package_write_allowed(package):
            return results
        if await self._is_large_super_package(package):
            return results
        return await self._search_source_in_package(search_query, max_results, object_type, package)

    @staticmethod
    def _description_words(description: str) -> str:
        return " ".join(description.casefold().replace("-", " ").replace("_", " ").split())

    def _sort_search_results(
        self, results: list[dict[str, Any]], sort_key: str
    ) -> list[dict[str, Any]]:
        """Sort search results by the given key."""
        if sort_key == "name":
            return sorted(results, key=lambda r: (r.get("name") or "").upper())
        if sort_key == "type":
            return sorted(results, key=lambda r: (r.get("type") or "").upper())
        if sort_key in ("last_changed", "lastchanged", "changed"):
            return sorted(results, key=lambda r: (r.get("lastChanged") or r.get("last_changed") or ""), reverse=True)
        return results

    async def _search_repository_objects(
        self,
        query: str,
        max_results: int = DEFAULT_MAX_RESULTS,
        object_type: str | None = None,
        package: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {"query": query, "maxResults": str(max(1, min(max_results, MAX_SEARCH_RESULTS_CAP)))}
        params["operation"] = "quickSearch"
        if object_type:
            params["objectType"] = object_type
        if package:
            params["packageName"] = package
        response = await self._request(
            "GET",
            f"{ADT_BASE_PATH}/repository/informationsystem/search",
            params=params,
            accept="application/*",
        )
        results = self._parse_search_results(response.text)
        await self._enrich_descriptions(results)
        return results

    async def _search_source_in_package(
        self,
        query: str,
        max_results: int,
        object_type: str | None,
        package: str,
    ) -> list[dict[str, Any]]:
        object_types = [self._canonical_object_type(object_type)] if object_type else [
            "CLAS",
            "INTF",
            "DDLS",
            "DCLS",
            "BDEF",
            "DDLX",
            "SRVD",
            "TABL",
            "DTEL",
            "DOMA",
        ]
        source_matches: list[dict[str, Any]] = []
        for source_object_type in object_types:
            objects = await self._search_repository_objects("*", MAX_SEARCH_RESULTS_CAP, self._repository_search_type(source_object_type), package)
            objects = self._filter_repository_objects(objects, source_object_type)
            for item in objects:
                name = item.get("name")
                if not name:
                    continue
                try:
                    source = await self.read_source(source_object_type or item.get("type", "CLAS"), name)
                except Exception:
                    continue
                source_matches.extend(self._source_matches(query, source, item))
                if len(source_matches) >= max_results:
                    return source_matches[:max_results]
        return source_matches[:max_results]

    async def list_package_objects(
        self,
        package: str,
        max_results: int = DEFAULT_PACKAGE_LIST_LIMIT,
        object_type: str | None = None,
    ) -> list[dict[str, Any]]:
        package_name = package.strip().upper()
        if not package_name:
            raise ValidationError("package is required")
        self._assert_package_read_allowed(package_name)
        search_type = self._repository_search_type(object_type)
        results = await self._search_repository_objects("*", max_results, search_type, package_name)
        return self._filter_repository_objects(results, object_type)

    async def object_exists(self, object_type: str, name: str) -> dict[str, Any]:
        object_name = name.strip().upper()
        if not object_name:
            raise ValidationError("name is required")
        registration = self._path_registration(object_type, SUPPORTED_TYPES_HELP)
        search_name = object_name
        if registration.canonical_type == "FUNC":
            _group_name, function_name = self._function_module_parts(object_name)
            search_name = function_name
        results = await self._search_repository_objects(search_name, DEFAULT_MAX_RESULTS, registration.search_type, None)
        results = self._filter_repository_objects(results, registration.canonical_type)
        match = self._exact_object_match(results, registration.canonical_type, object_name)
        return {
            "exists": match is not None,
            "object_type": registration.canonical_type,
            "name": object_name,
            "object": match,
        }

    async def _is_large_super_package(self, package: str) -> bool:
        try:
            metadata = await self._request(
                "GET",
                f"{ADT_BASE_PATH}/packages/{quote(package.lower())}",
                accept="application/vnd.sap.adt.packages.v2+xml, application/xml, */*",
            )
        except Exception:
            return False
        subpackages = 0
        inside_subpackages = False
        for event, elem in ET.iterparse(io.StringIO(metadata.text), events=("start", "end")):
            tag = elem.tag.rsplit("}", 1)[-1]
            if event == "start" and tag == "subPackages":
                inside_subpackages = True
            elif event == "end" and tag == "subPackages":
                inside_subpackages = False
            elif event == "start" and inside_subpackages and tag == "packageRef":
                subpackages += 1
                if subpackages > LARGE_PACKAGE_THRESHOLD:
                    return True
        return False

    def _source_matches(self, query: str, source_result: dict[str, Any], repository_item: dict[str, Any]) -> list[dict[str, Any]]:
        needle = query.casefold()
        if not needle:
            return []
        parts = source_result.get("source_parts") or [
            {
                "include_type": source_result.get("source_part", "main"),
                "uri": source_result.get("uri"),
                "source": source_result.get("source", ""),
            }
        ]
        matches: list[dict[str, Any]] = []
        for part in parts:
            source = part.get("source", "")
            for line_number, line in enumerate(source.splitlines(), start=1):
                if needle not in line.casefold():
                    continue
                parent_name = repository_item.get("name", source_result.get("name", ""))
                include_type = part.get("include_type", "main")
                uri = part.get("uri", source_result.get("uri", ""))
                matches.append(
                    {
                        "uri": f"{uri}#line={line_number}",
                        "type": "SOURCE/LOCAL",
                        "name": f"{parent_name}:{include_type}:{line_number}",
                        "packageName": repository_item.get("packageName"),
                        "description": f"Source match in {parent_name} {include_type} line {line_number}",
                        "parentUri": repository_item.get("uri"),
                        "parentType": repository_item.get("type"),
                        "parentName": parent_name,
                        "includeType": include_type,
                        "line": line_number,
                        "match": line.strip(),
                    }
                )
        return matches

    def _canonical_object_type(self, object_type: str) -> str:
        return self._path_registration(object_type, SUPPORTED_TYPES_HELP).canonical_type

    def _repository_search_type(self, object_type: str | None) -> str | None:
        if not object_type:
            return None
        return self._path_registration(object_type, SUPPORTED_SEARCH_TYPES_HELP).search_type

    def _filter_repository_objects(
        self, results: list[dict[str, Any]], object_type: str | None
    ) -> list[dict[str, Any]]:
        if not object_type:
            return results
        canonical_type = self._canonical_object_type(object_type)
        return [item for item in results if self._repository_item_matches_type(item, canonical_type)]

    def _repository_item_matches_type(self, item: dict[str, Any], canonical_type: str) -> bool:
        item_type = (item.get("type") or "").upper()
        base_type = item_type.split("/", 1)[0]
        if canonical_type == "FUNC":
            return item_type == "FUGR/FF" or base_type == "FUNC"
        if canonical_type == "FUGR":
            return item_type in {"", "FUGR", "FUGR/F"}
        return not item_type or base_type == canonical_type

    def _exact_object_match(
        self, results: list[dict[str, Any]], canonical_type: str, object_name: str
    ) -> dict[str, Any] | None:
        for item in results:
            item_name = (item.get("name") or "").upper()
            item_type = (item.get("type") or "").upper()
            base_type = item_type.split("/", 1)[0]
            if canonical_type == "FUNC" and item_name == object_name and item_type == "FUGR/FF":
                return item
            if canonical_type == "FUNC" and object_name.endswith(f"/{item_name}") and item_type in {"", "FUGR/FF", "FUNC"}:
                return item
            if item_name == object_name and (not base_type or base_type == canonical_type):
                return item
        return None

    def _parse_search_results(self, text: str) -> list[dict[str, Any]]:
        if not text.strip():
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return [{"raw": text}]
        results = []
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag not in {"objectReference", "entry"}:
                continue
            item = {
                self._clean_xml_name(key): value.strip() if isinstance(value, str) else value
                for key, value in element.attrib.items()
            }
            title = element.find("{http://www.w3.org/2005/Atom}title")
            if title is not None and title.text:
                item["title"] = title.text.strip()
            if item:
                results.append(item)
        return results

    async def _enrich_descriptions(self, results: list[dict[str, Any]]) -> None:
        for item in results:
            if item.get("description"):
                continue
            object_type = item.get("type", "")
            uri = item.get("uri")
            if not uri or not object_type.startswith("CLAS/"):
                continue
            try:
                response = await self._request(
                    "GET",
                    uri,
                    accept="application/vnd.sap.adt.oo.classes.v4+xml, application/xml, */*",
                )
                root = ET.fromstring(response.text)
            except Exception:
                continue
            description = root.attrib.get("{http://www.sap.com/adt/core}description")
            if description:
                item["description"] = description
