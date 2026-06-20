from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

from sap_mcp.connectors.core.registry import (
    ADT_BASE_PATH,
    ADT_PATH_REGISTRATIONS,
    ADT_PATH_REGISTRY_BY_ALIAS,
    SUPPORTED_SOURCE_TYPES_HELP,
    SUPPORTED_TYPES_HELP,
    SUPPORTED_WRITABLE_TYPES_HELP,
    AdtPathRegistration,
    SourceTarget,
)
from sap_mcp.errors import SapBackendError, ValidationError


def coerce_adt_path(uri: str) -> str:
    """Normalize a raw URI to an ADT path.

    Preserves percent-encoding (e.g. %2f) so that namespaced object
    names like /DMO/... remain correctly encoded as %2fDMO%2f...
    instead of creating double-slash paths.

    This is a module-level utility shared by AdtPathMixin and BaseMixin.
    """
    value = uri.strip()
    parsed = urlparse(value)
    if parsed.scheme and parsed.path:
        value = parsed.path
    if "/sap/bc/adt/" in value and not value.startswith("/sap/bc/adt/"):
        value = value[value.index("/sap/bc/adt/"):]
    # Strip fragment and query params but preserve path encoding
    value = value.split("#", 1)[0].split("?", 1)[0]
    if not value.startswith("/sap/bc/adt/"):
        raise ValidationError("URI must contain an ADT /sap/bc/adt path")
    return value


class AdtPathMixin:
    """Core path resolution for ABAP objects.

    References:
      - source_suffix: used in _source_path.
      - read_suffix / read_kind: used in _read_path.
      - source_search: controls enablement in _is_source_search_type.
      - oo_source: controls OO include resolution in _is_oo_source_type.
    """

    # ── Source / Object Path Resolution ──────────────────────────────────

    def _source_path(self, object_type: str, name: str) -> str:
        reg = self._path_registration(object_type, supported_types=SUPPORTED_SOURCE_TYPES_HELP)
        path = self._resolve_registration_path(reg, name)
        if reg.source_suffix:
            return f"{path}/{reg.source_suffix}"
        return path

    def _object_path(self, object_type: str, name: str) -> str:
        registration = self._path_registration(object_type, SUPPORTED_TYPES_HELP)
        return self._resolve_registration_path(registration, name)

    def _collection_path(self, object_type: str, name_part: str | None = None) -> str:
        registration = self._path_registration(object_type, SUPPORTED_TYPES_HELP)
        path = self._resolve_registration_path(registration, name_part or "", for_collection=True)
        return path

    def _read_path(self, object_type: str, name: str) -> str:
        registration = self._path_registration(object_type, SUPPORTED_SOURCE_TYPES_HELP)
        path = self._resolve_registration_path(registration, name)
        suffix = registration.read_suffix
        if suffix:
            return f"{path}/{suffix}"
        return path

    def _metadata_path(self, object_type: str | None = None, name: str | None = None, uri: str | None = None) -> str:
        if uri:
            path = self._coerce_adt_path(uri)
            if "/sap/bc/adt/businessservices/odatav" in path.lower():
                binding_name = path.rsplit("/", 1)[-1].split("?")[0]
                if "?" not in path:
                    path = f"{path}?servicename={quote(binding_name.upper())}"
            return path
        if not object_type or not name:
            raise ValidationError("Provide either 'uri' or both 'object_type' and 'name' for metadata")
        registration = self._find_path_registration(object_type)
        if not registration:
            raise ValidationError(f"Unsupported object type: {object_type}")
        path = self._resolve_registration_path(registration, name)
        if registration.oo_source:
            return f"{path}/objectstructure"
        return path

    def _function_module_parts(self, name: str) -> tuple[str, str]:
        parts = name.split("/", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return "", parts[0]

    def _function_module_name(self, parent: str, name: str) -> str:
        return f"{parent}/{name}" if parent else name

    def _adt_object_type(self, object_type: str) -> str:
        registration = self._path_registration(object_type, SUPPORTED_TYPES_HELP)
        return registration.search_type or registration.canonical_type

    def _adt_object_name(self, object_type: str, name: str) -> str:
        object_name = name.strip().upper()
        registration = self._path_registration(object_type, SUPPORTED_TYPES_HELP)
        if registration.canonical_type == "FUNC":
            _group_name, function_name = self._function_module_parts(object_name)
            return function_name
        return object_name

    async def _resolve_repository_object_name(self, object_type: str | None, name: str | None) -> str | None:
        if not object_type or not name:
            return name
        object_name = name.strip().upper()
        if not object_name:
            return name
        registration = self._path_registration(object_type, SUPPORTED_TYPES_HELP)
        if registration.canonical_type != "FUNC" or "/" in object_name:
            return object_name
        resolved_name = await self._resolve_function_module_name_from_repository(registration, object_name)
        if resolved_name:
            return resolved_name
        raise ValidationError(
            f"Function module {object_name} was not found through ADT Repository Information System. "
            "Pass the fully qualified name as FUNCTION_GROUP/FUNCTION_MODULE if the object is not searchable."
        )

    async def _resolve_function_module_name_from_repository(
        self, registration: AdtPathRegistration, function_name: str
    ) -> str | None:
        matches = await self._search_repository_objects(function_name, 10, registration.search_type, None)
        for match in matches:
            if (match.get("name") or "").upper() != function_name:
                continue
            uri = match.get("uri")
            if not uri:
                continue
            resolved_name = self._match_registration_name(uri, registration)
            if resolved_name and resolved_name.endswith(f"/{function_name}"):
                return resolved_name
        return None

    # ── Object Type Resolution ──────────────────────────────────────────

    def _path_registration(self, object_type: str, supported_types: str = SUPPORTED_TYPES_HELP) -> AdtPathRegistration:
        if not object_type or not object_type.strip():
            raise ValidationError("object_type is required")
        canonical = self._canonical_type(object_type)
        registration = ADT_PATH_REGISTRY_BY_ALIAS.get(canonical.lower())
        if registration is None:
            raise ValidationError(f"Unsupported object type '{object_type}'. {supported_types}")
        return registration

    def _find_path_registration(self, object_type: str) -> AdtPathRegistration | None:
        if not object_type or not object_type.strip():
            return None
        try:
            canonical = self._canonical_type(object_type)
        except (ValidationError, ValueError):
            return None
        result = ADT_PATH_REGISTRY_BY_ALIAS.get(canonical.lower())
        if result is None:
            return None
        if result.canonical_type.upper() != canonical.upper():
            return ADT_PATH_REGISTRY_BY_ALIAS.get(canonical.lower())
        return result

    @staticmethod
    def _canonical_type(object_type: str) -> str:
        """Normalize an object type string to a canonical type.

        Accepts aliases (e.g. "clas", "class") and canonical forms (e.g. "CLAS/OC").
        Returns the canonical type string (e.g. "CLAS", "INTF", "DDLS").
        """
        lookup = object_type.strip().lower()
        for registration in ADT_PATH_REGISTRATIONS:
            if lookup in registration.aliases or lookup == registration.canonical_type.lower():
                return registration.canonical_type
            if "/" in lookup:
                base, *_ = lookup.split("/", 1)
                if base in registration.aliases or base == registration.canonical_type.lower():
                    return registration.canonical_type
        raise ValidationError(f"Unsupported object type '{object_type}'")

    def _canonical_object_type(self, object_type: str) -> str:
        return self._canonical_type(object_type)

    # ── URI / ADT Path Helpers ──────────────────────────────────────────

    def _coerce_adt_path(self, uri: str) -> str:
        """Normalize a raw URI to an ADT path (delegates to module-level utility)."""
        return coerce_adt_path(uri)

    def _adt_relative_url(self, *parts: str) -> str:
        """Join path segments relative to ADT_BASE_PATH.

        - Absolute href (starting with /sap/bc/adt/): returned as-is.
        - First part starts with /sap/bc/adt/: use it as base, join remaining.
        - Otherwise: join all parts under ADT_BASE_PATH.
        """
        if not parts:
            return ADT_BASE_PATH
        href = parts[-1]
        stripped_href = href.lstrip("/")
        if stripped_href.startswith(f"{ADT_BASE_PATH.lstrip('/')}/"):
            idx = stripped_href.index(ADT_BASE_PATH.lstrip("/"))
            return f"/{stripped_href[idx:]}"
        if parts[0].startswith(f"{ADT_BASE_PATH}/"):
            rest = [p.strip("/") for p in parts[1:] if p.strip("/")]
            return urljoin(parts[0].rstrip("/") + "/", "/".join(rest)) if rest else parts[0]
        stripped = [p.strip("/") for p in parts if p.strip("/")]
        return urljoin(ADT_BASE_PATH + "/", "/".join(stripped))

    def _adt_api_path(self, uri_or_path: str) -> str:
        """Normalize an ADT URI or path to a local path string."""
        return self._coerce_adt_path(uri_or_path)

    @staticmethod
    def _path_root(path: str) -> str:
        return path.split("{", 1)[0].rstrip("/")

    @staticmethod
    def _join_path(base: str, *parts: str) -> str:
        result = base.rstrip("/")
        for part in parts:
            result = f"{result}/{part.strip('/')}"
        return result

    def _normalize_business_service_info_uri(self, uri: str, binding_name: str) -> str:
        path = self._coerce_adt_path(uri)
        if "?" not in path:
            path = f"{path}?servicename={quote(binding_name.upper())}"
        return path

    def _normalize_odata_version(self, version: str | None, default: str = "V4") -> str:
        if version is None:
            return default
        normalized = version.upper().replace("\\", "").replace(" ", "")
        if normalized in {"V2", "2", "ODATAV2"}:
            return "V2"
        if normalized in {"V4", "4", "ODATAV4"}:
            return "V4"
        raise ValidationError(f"Unsupported OData version: {version}. Use V2 or V4.")

    # ── Object Reference / URI Matching ──────────────────────────────────

    def _object_ref_from_any_uri(self, uri: str) -> dict[str, str]:
        path = self._coerce_adt_path(uri)
        for registration in ADT_PATH_REGISTRATIONS:
            name = self._match_registration_name(path, registration)
            if name:
                return {"type": registration.canonical_type, "name": name}
        raise ValidationError(f"Cannot infer ABAP object from URI: {uri}")

    def _match_registration_name(self, path: str, registration: AdtPathRegistration) -> str | None:
        if registration.canonical_type == "FUNC":
            match = re.match(
                r"^/sap/bc/adt/functions/groups/([^/]+)/fmodules/([^/]+)", path, re.IGNORECASE
            )
            if match:
                return f"{unquote(match.group(1)).upper()}/{unquote(match.group(2)).upper()}"
            return None
        prefix = self._path_root(registration.root_template)
        if not path.lower().startswith(prefix.lower()):
            return None
        name = path[len(prefix):].strip("/").split("/", 1)[0]
        return unquote(name).upper() if name else None

    def _match_registration_source_path(
        self, path: str, registration: AdtPathRegistration
    ) -> str | None:
        if registration.canonical_type == "FUNC":
            match = re.match(
                r"^/sap/bc/adt/functions/groups/([^/]+)/fmodules/([^/]+)", path, re.IGNORECASE
            )
            if match:
                return f"{unquote(match.group(1)).upper()}/{unquote(match.group(2)).upper()}"
            return None
        root = self._path_root(registration.root_template)
        if not path.lower().startswith(root.lower()):
            return None
        suffix = registration.source_suffix or registration.read_suffix
        if suffix:
            remainder = path[len(root):].strip("/")
            if remainder.endswith(suffix) and len(remainder) > len(suffix):
                candidate = remainder[: -len(suffix)].rstrip("/")
                if candidate and "/" not in candidate:
                    return unquote(candidate).upper()
            # if the path ends with raw object (no suffix), parse directly
            if remainder and "/" not in remainder:
                return unquote(remainder).upper()
        return self._match_registration_name(path, registration)

    # ── Source Target Resolution ─────────────────────────────────────────

    def _resolve_source_target(
        self,
        object_type: str | None,
        name: str | None,
        scope: str | None,
        include_type: str | None,
        uri: str | None,
        for_write: bool = False,
    ) -> SourceTarget:
        if uri:
            return self._source_target_from_uri(uri)

        if not object_type or not name:
            raise ValidationError("Provide either 'uri' or both 'object_type' and 'name'")

        object_name = name.strip().upper()
        if not object_name:
            raise ValidationError("name cannot be empty")

        registration = self._path_registration(object_type, SUPPORTED_SOURCE_TYPES_HELP)
        resolved_object_type = registration.canonical_type

        normalized_scope = self._normalize_scope(scope)
        normalized_include = self._normalize_include_type(include_type) if include_type else None

        if normalized_scope == "include" and normalized_include:
            # Include path (e.g. definitions, implementations)
            root = self._resolve_registration_path(registration, object_name)
            # OO classes/interfaces have separate include endpoints
            from urllib.parse import quote

            normalized_type = resolved_object_type.lower()
            if normalized_type in ("clas", "intf"):
                # Fetch the metadata to discover include URIs
                metadata_uri = self._metadata_path(resolved_object_type, object_name)
            path = f"{root}/includes/{normalized_include}"
            return SourceTarget(
                object_type=resolved_object_type,
                name=object_name,
                uri=path,
                source_kind="source",
                scope="include",
                include_type=normalized_include,
                round_trippable=True,
                read_hint=self._build_read_hint(resolved_object_type, object_name, "include", normalized_include),
            )

        if normalized_scope == "main" or normalized_include == "main" or (normalized_scope is None and normalized_include is None):
            path = self._read_path(resolved_object_type, object_name)
            object_type_text = resolved_object_type
            read_hint = self._build_read_hint(resolved_object_type, object_name)
            return SourceTarget(
                object_type=resolved_object_type,
                name=object_name,
                uri=path,
                source_kind="source",
                scope="main",
                round_trippable=True,
                read_hint=read_hint,
            )

        raise ValidationError(
            f"Unsupported scope '{scope}' for include_type '{include_type}'. "
            "Use scope='main' for main source or scope='include' with a valid include_type."
        )

    def _source_target_from_uri(self, uri: str) -> SourceTarget:
        path = self._coerce_adt_path(uri)
        for registration in ADT_PATH_REGISTRATIONS:
            name = self._match_registration_source_path(path, registration)
            if name:
                suffix = registration.source_suffix or registration.read_suffix
                is_source = suffix and suffix in path
                scope = "include" if "includes/" in path else "main"
                include_type = self._include_type_from_source_part(path)
                source_kind = "source" if is_source else "metadata"
                return SourceTarget(
                    object_type=registration.canonical_type,
                    name=name,
                    uri=path,
                    source_kind=source_kind,
                    scope=scope,
                    include_type=include_type,
                    round_trippable=True,
                    read_hint=self._build_read_hint(
                        registration.canonical_type, name, scope=scope, include_type=include_type
                    ),
                )
        raise ValidationError(f"Cannot resolve source target from URI: {uri}")

    def _registered_source_target_from_uri(self, uri: str) -> SourceTarget | None:
        path = self._coerce_adt_path(uri)
        for registration in ADT_PATH_REGISTRATIONS:
            name = self._match_registration_source_path(path, registration)
            if name:
                suffix = registration.source_suffix or registration.read_suffix
                is_source = suffix and suffix in path
                scope = "include" if "includes/" in path else "main"
                include_type = self._include_type_from_source_part(path)
                return SourceTarget(
                    object_type=registration.canonical_type,
                    name=name,
                    uri=path,
                    source_kind="source" if is_source else "metadata",
                    scope=scope,
                    include_type=include_type,
                    round_trippable=True,
                    read_hint=self._build_read_hint(registration.canonical_type, name),
                )
        return None

    def _normalize_scope(self, scope: str | None) -> str | None:
        if scope is None:
            return None
        normalized = scope.strip().lower()
        if normalized in ("main", "all", "full"):
            return "main"
        if normalized == "include":
            return "include"
        if normalized in ("with_includes", "with_includes"):
            return "with_includes"
        if normalized in ("active", "version_active", "version_active"):
            return "active"
        if normalized in ("inactive", "version_inactive", "version_inactive"):
            return "inactive"
        if normalized == "both":
            return "both"
        raise ValidationError(
            f"Invalid scope '{scope}'. Valid scopes: main, include, with_includes, active, inactive, both"
        )

    def _normalize_include_type(self, include_type: str) -> str:
        """Normalize an OO include type name.

        Accepted: definitions, implementations, macros, testclasses.
        """
        normalized = include_type.strip().lower()
        include_types = {"definitions", "implementations", "macros", "testclasses"}
        if normalized in include_types:
            return normalized
        raise ValidationError(
            f"Invalid include_type '{include_type}'. "
            f"Valid types: {', '.join(sorted(include_types))}"
        )

    def _include_type_from_source_part(self, path: str) -> str | None:
        """Extract include type from a source path.

        e.g. /sap/bc/adt/oo/classes/zcl_foo/includes/definitions -> "definitions"
        """
        match = re.search(
            r"(?:^|/)includes/(?P<include>definitions|implementations|macros|testclasses)(?:$|[?#])",
            path,
        )
        if match:
            return self._normalize_include_type(match.group("include"))
        return None

    def _build_read_hint(
        self,
        object_type: str,
        name: str,
        scope: str = "main",
        include_type: str | None = None,
    ) -> str:
        """Build a context-specific hint for re-reading the source."""
        if scope == "include" and include_type:
            return (
                f"use abap_read_source(object_type=\"{object_type}\", name=\"{name}\", "
                f"scope=\"include\", include_type=\"{include_type}\")"
            )
        return f"use abap_read_source(object_type=\"{object_type}\", name=\"{name}\", scope=\"main\")"

    # ── Type Classification ──────────────────────────────────────────────

    def _is_oo_source_type(self, object_type: str) -> bool:
        registration = self._find_path_registration(object_type)
        return registration is not None and registration.oo_source

    def _is_source_search_type(self, object_type: str) -> bool:
        registration = self._find_path_registration(object_type)
        return registration is not None and registration.source_search

    def _oo_source_part(self, object_type: str) -> str:
        registration = self._find_path_registration(object_type)
        if registration and registration.oo_source:
            return registration.source_suffix or "source/main"
        return ""

    def _is_metadata_write_path(self, path: str) -> bool:
        return path.endswith(("/objectstructure", "/metadata")) or "/objectstructure" in path

    def _augment_update_error(self, error: SapBackendError, target: SourceTarget) -> SapBackendError:
        """Wrap a SapBackendError with additional source-target context."""
        if not error.details:
            error.details = {}
        error.details["read_hint"] = target.read_hint
        return error

    # ── Template Helpers ─────────────────────────────────────────────────

    def _resolve_registration_path(
        self,
        registration: AdtPathRegistration,
        name: str,
        for_collection: bool = False,
    ) -> str:
        """Resolve a canonical path for the given registration and object name.

        Uses safe='' to encode forward slashes in namespaced names (e.g. /DMO/...)
        as %2f, preventing them from being interpreted as path separators.
        """
        from urllib.parse import quote

        if registration.canonical_type == "FUNC":
            group_name, function_name = self._function_module_parts(name)
            return registration.root_template.format(
                group_name=quote(group_name.lower(), safe="").lower(),
                function_name=quote(function_name.lower(), safe="").lower(),
            )

        # Lowercase hex digits to match ADT server URI format (%2f not %2F)
        quoted = quote(name.lower(), safe="").lower()

        if for_collection and registration.collection_template:
            if "{name}" in registration.collection_template:
                return registration.collection_template.format(name=quoted)
            return registration.collection_template

        # For FUNC type, handle collection path separately
        if for_collection:
            root = self._path_root(registration.root_template)
            return f"{root}/{quoted}"

        return registration.root_template.format(name=quoted)

    # ── Shared Utilities ─────────────────────────────────────────────────

    def _default_source(self, object_type: str, name: str) -> str:
        """Dummy default source for ADT object creation.

        See AdtCreationMixin for a richer default source implementation.
        """
        registration = self._find_path_registration(object_type)
        if registration:
            if registration.canonical_type in ("BDEF", "SRVD", "SRVB"):
                return ""
            if registration.create_adt_type:
                # Needs XML metadata, not plain ABAP source
                return ""
            return f'{name} = "Initial source; replace with actual ABAP code."'
        return f'{name} = "Initial source; replace with actual ABAP code."'

    def _object_set_xml(
        self,
        objects: list[dict[str, str]] | None,
        packages: list[str] | None,
        include_subpackages: bool,
        namespace: str = "aunit",
    ) -> str:
        """Build an object-set XML element for ABAP Unit / ATC requests."""
        if not objects and not packages:
            raise ValidationError("At least one object or package is required")

        # Validate
        for item in objects or []:
            obj_type = (item.get("type") or item.get("object_type") or "").strip()
            obj_name = (item.get("name") or "").strip()
            if not obj_type or not obj_name:
                raise ValidationError("Each object must contain name and type/object_type")

        if namespace == "objectset":
            return self._object_set_xml_for_atc(objects or [], packages or [], include_subpackages)

        result = ""
        if packages:
            for package in packages:
                package_name = package.strip().upper()
                if package_name:
                    self._assert_package_read_allowed(package_name) if hasattr(self, "_assert_package_read_allowed") else None
                    include = "true" if include_subpackages else "false"
                    result += f'<aunit:package_name value="{self._xml_escape(package_name)}" includeSubpackages="{include}"/>'

        if objects:
            for item in objects:
                obj_type = (item.get("type") or item.get("object_type") or "").upper()
                obj_name = (item.get("name") or "").upper()
                result += f'<aunit:object_name type="{self._xml_escape(obj_type)}" name="{self._xml_escape(obj_name)}"/>'

        return f"<aunit:objects>{result}</aunit:objects>"

    def _object_set_xml_for_atc(
        self,
        objects: list[dict[str, str]],
        packages: list[str],
        include_subpackages: bool,
    ) -> str:
        sets: list[str] = []
        for package in packages:
            package_name = package.strip().upper()
            if package_name:
                self._assert_package_read_allowed(package_name) if hasattr(self, "_assert_package_read_allowed") else None
                include = "true" if include_subpackages else "false"
                sets.append(
                    f'<osl:set xsi:type="osl:packageSet">'
                    f'<osl:package includeSubpackages="{include}" name="{self._xml_escape(package_name)}"/>'
                    f"</osl:set>")
        object_xml: list[str] = []
        for item in objects:
            obj_type = (item.get("type") or item.get("object_type") or "").upper()
            obj_name = (item.get("name") or "").upper()
            object_xml.append(f'<osl:object name="{self._xml_escape(obj_name)}" type="{self._xml_escape(obj_type)}"/>')
        if object_xml:
            sets.append(f'<osl:set xsi:type="osl:flatObjectSet">{"".join(object_xml)}</osl:set>')
        return (
            '<osl:objectSet xsi:type="unionSet" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:osl="http://www.sap.com/adt/objectset">'
            f'{"".join(sets)}</osl:objectSet>')

    def _initial_create_source(self, registration: AdtPathRegistration, name: str, description: str) -> str:
        """Minimal source template for new object creation."""
        if not registration.root_template:
            return ""
        path = self._resolve_registration_path(registration, name)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<abap:abap program="{name}" xmlns:abap="http://www.sap.com/adt/abap">'
            f"</abap:abap>"
        )
