from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, unquote, urljoin

from sap_mcp.connectors.adt_registry import ADT_PATH_REGISTRY_BY_ALIAS, AdtPathRegistration, SourceTarget
from sap_mcp.errors import SapBackendError, ValidationError


class AdtPathMixin:
    def _source_path(self, object_type: str, name: str) -> str:
        registration = self._path_registration(
            object_type,
            "Writable types are class, interface, ddls/cds, dcls/dcl, bdef, ddlx, srvd, srvb, tabl, dtel, doma, devc, prog, fugr, and func",
        )
        root = self._path_root(registration, name)
        if registration.oo_source:
            source_part = self._oo_source_part(object_type)
            if source_part in {"metadata", "texts"}:
                raise ValidationError(
                    f"{registration.display_name} metadata and text elements are read-only through abap_update_source"
                )
            return self._join_path(root, source_part)
        return self._join_path(root, registration.source_suffix)

    def _metadata_path(self, object_type: str | None, name: str | None, uri: str | None) -> str:
        if uri:
            return self._normalize_business_service_info_uri(self._adt_api_path(uri))
        if not object_type or not name:
            raise ValidationError("Provide uri or object_type and name")
        return self._object_path(object_type, name)

    def _resolve_source_target(
        self,
        object_type: str | None,
        name: str | None,
        scope: str | None,
        include_type: str | None,
        uri: str | None,
        *,
        for_write: bool = False,
    ) -> SourceTarget:
        if uri:
            return self._source_target_from_uri(uri, object_type, name, for_write=for_write)

        if not object_type or not name:
            raise ValidationError("Provide uri or object_type and name")

        registration = self._path_registration(
            object_type,
            "Supported source types are class, interface, ddls/cds, dcls/dcl, bdef, ddlx, srvd, tabl, dtel, doma, devc, srvb, prog, fugr, and func",
        )
        object_name = name.strip().upper()
        read_hint = self._build_read_hint(registration.canonical_type, object_name, scope, include_type)
        if registration.oo_source:
            return self._resolve_oo_source_target(object_type, object_name, scope, include_type, read_hint, for_write=for_write)

        normalized_scope = self._normalize_scope(scope)
        if normalized_scope == "with_includes":
            raise ValidationError(f"{registration.display_name} does not support scope=with_includes")
        if include_type:
            raise ValidationError(f"{registration.display_name} does not support include_type")
        uri_path = self._source_path(object_type if for_write else registration.canonical_type, object_name)
        return SourceTarget(
            object_type=registration.canonical_type,
            name=object_name,
            uri=uri_path,
            source_kind="metadata" if self._is_metadata_write_path(uri_path) else "source",
            scope="main",
            round_trippable=True,
            read_hint=read_hint,
        )

    def _resolve_oo_source_target(
        self,
        object_type: str,
        name: str,
        scope: str | None,
        include_type: str | None,
        read_hint: str,
        *,
        for_write: bool,
    ) -> SourceTarget:
        registration = self._path_registration(
            object_type,
            "Supported source types are class and interface",
        )
        root = self._path_root(registration, name)
        explicit_part = self._oo_source_part(object_type)
        explicit_include = self._include_type_from_source_part(explicit_part)
        normalized_scope = self._normalize_scope(scope)
        if explicit_include and scope is None:
            normalized_scope = "include"

        if explicit_part == "metadata":
            if include_type or normalized_scope in {"include", "with_includes"}:
                raise ValidationError(f"{registration.display_name} metadata does not support include selection")
            return SourceTarget(
                object_type=registration.canonical_type,
                name=name,
                uri=root,
                source_kind="metadata",
                scope="main",
                round_trippable=not for_write,
                read_hint=self._build_read_hint(registration.canonical_type, name, "main", None),
            )
        if explicit_part == "texts":
            if include_type or normalized_scope in {"include", "with_includes"}:
                raise ValidationError(f"{registration.display_name} text elements do not support include selection")
            if not registration.texts_template:
                raise ValidationError(f"{registration.display_name} text elements are not registered")
            return SourceTarget(
                object_type=registration.canonical_type,
                name=name,
                uri=registration.texts_template.format(name=quote(name.lower())),
                source_kind="metadata",
                scope="main",
                round_trippable=False,
                read_hint=self._build_read_hint(registration.canonical_type, name, "main", None),
            )

        if normalized_scope == "with_includes":
            if explicit_include:
                raise ValidationError("scope=with_includes cannot be combined with an include-specific object_type")
            return SourceTarget(
                object_type=registration.canonical_type,
                name=name,
                uri=self._join_path(root, "source/main"),
                source_kind="source_with_includes",
                scope="with_includes",
                round_trippable=False,
                read_hint=self._build_read_hint(registration.canonical_type, name, "include", "implementations"),
            )

        target_include = self._normalize_include_type(include_type or explicit_include)
        if normalized_scope == "include" and not target_include:
            raise ValidationError("scope=include requires include_type")
        if normalized_scope == "main" and target_include:
            raise ValidationError("scope=main cannot be combined with include_type")

        if target_include:
            uri = self._join_path(root, f"includes/{target_include}")
            return SourceTarget(
                object_type=registration.canonical_type,
                name=name,
                uri=uri,
                source_kind="source",
                scope="include",
                include_type=target_include,
                round_trippable=True,
                read_hint=self._build_read_hint(registration.canonical_type, name, "include", target_include),
            )

        return SourceTarget(
            object_type=registration.canonical_type,
            name=name,
            uri=self._join_path(root, "source/main"),
            source_kind="source",
            scope="main",
            round_trippable=True,
            read_hint=self._build_read_hint(registration.canonical_type, name, "main", None),
        )

    def _source_target_from_uri(
        self,
        uri: str,
        object_type: str | None = None,
        name: str | None = None,
        *,
        for_write: bool = False,
    ) -> SourceTarget:
        path = self._adt_api_path(uri)
        match = re.match(
            r"^/sap/bc/adt/oo/(?P<collection>classes|interfaces)/(?P<name>[^/]+)"
            r"(?:/(?P<section>source/main|includes/(?P<include>definitions|implementations|macros|testclasses)))?$",
            path,
            flags=re.IGNORECASE,
        )
        if match:
            collection = match.group("collection").lower()
            canonical_type = "CLAS" if collection == "classes" else "INTF"
            object_name = (name or unquote(match.group("name"))).upper()
            if object_type and self._path_registration(object_type, "Supported source types are class and interface").canonical_type != canonical_type:
                raise ValidationError(f"Provided uri {path} does not match object_type {object_type}")
            if name and name.strip().upper() != object_name:
                raise ValidationError(f"Provided uri {path} does not match name {name}")
            include = match.group("include")
            if include:
                return SourceTarget(
                    object_type=canonical_type,
                    name=object_name,
                    uri=path,
                    source_kind="source",
                    scope="include",
                    include_type=include.lower(),
                    round_trippable=True,
                    read_hint=self._build_read_hint(canonical_type, object_name, "include", include.lower()),
                )
            source_kind = "metadata" if match.group("section") is None else "source"
            return SourceTarget(
                object_type=canonical_type,
                name=object_name,
                uri=path,
                source_kind=source_kind,
                scope="main",
                round_trippable=source_kind == "source",
                read_hint=self._build_read_hint(canonical_type, object_name, "main", None),
            )

        if object_type and name:
            target = self._resolve_source_target(object_type, name, "main", None, None, for_write=for_write)
            if target.uri != path:
                raise ValidationError(
                    f"Provided uri {path} does not match resolved source uri {target.uri} for {object_type} {name}"
                )
            return target
        target = self._registered_source_target_from_uri(path, object_type, name, for_write=for_write)
        if target:
            return target
        raise ValidationError(
            "uri-only source operations support registered ADT source URIs such as "
            "CLAS/INTF main/includes, DDLS, DCLS, BDEF, DDLX, SRVD, TABL, PROG, and FUNC"
        )

    def _registered_source_target_from_uri(
        self,
        path: str,
        object_type: str | None,
        name: str | None,
        *,
        for_write: bool,
    ) -> SourceTarget | None:
        for registration in ADT_PATH_REGISTRY_BY_ALIAS.values():
            if registration.oo_source or not registration.source_suffix:
                continue
            match = self._match_registration_source_path(registration, path)
            if not match:
                continue
            canonical_type = registration.canonical_type
            object_name = (name or match.get("name") or match.get("function_name") or "").upper()
            if canonical_type == "FUNC":
                group_name = (match.get("group_name") or "").upper()
                function_name = (match.get("function_name") or "").upper()
                object_name = name.upper() if name else f"{group_name}/{function_name}"
            if object_type and self._path_registration(object_type, "Unsupported source type").canonical_type != canonical_type:
                raise ValidationError(f"Provided uri {path} does not match object_type {object_type}")
            if name and name.strip().upper() != object_name:
                raise ValidationError(f"Provided uri {path} does not match name {name}")
            return SourceTarget(
                object_type=canonical_type,
                name=object_name,
                uri=path,
                source_kind=registration.read_kind,
                scope="main",
                round_trippable=registration.read_kind == "source",
                read_hint=self._build_read_hint(canonical_type, object_name, "main", None, path),
            )
        return None

    def _match_registration_source_path(self, registration: AdtPathRegistration, path: str) -> dict[str, str] | None:
        root_pattern = re.escape(registration.root_template)
        root_pattern = root_pattern.replace(re.escape("{name}"), r"(?P<name>[^/]+)")
        root_pattern = root_pattern.replace(re.escape("{group_name}"), r"(?P<group_name>[^/]+)")
        root_pattern = root_pattern.replace(re.escape("{function_name}"), r"(?P<function_name>[^/]+)")
        pattern = rf"^{root_pattern}/{re.escape(registration.source_suffix or '').replace('/', r'/')}$"
        match = re.match(pattern, path, flags=re.IGNORECASE)
        if not match:
            return None
        return {key: unquote(value) for key, value in match.groupdict(default="").items()}

    def _normalize_scope(self, scope: str | None) -> str:
        requested = (scope or "main").strip().lower().replace("-", "_")
        aliases = {
            "": "main",
            "main": "main",
            "source": "main",
            "include": "include",
            "part": "include",
            "with_includes": "with_includes",
            "composite": "with_includes",
            "all": "with_includes",
        }
        normalized = aliases.get(requested)
        if not normalized:
            raise ValidationError("scope must be one of: main, include, with_includes")
        return normalized

    def _normalize_include_type(self, include_type: str | None) -> str | None:
        if not include_type:
            return None
        requested = include_type.strip().lower().replace("-", "_")
        include_parts = {
            "definitions": "definitions",
            "definition": "definitions",
            "local_definitions": "definitions",
            "implementations": "implementations",
            "implementation": "implementations",
            "local_implementations": "implementations",
            "macros": "macros",
            "testclasses": "testclasses",
            "test_classes": "testclasses",
            "tests": "testclasses",
        }
        normalized = include_parts.get(requested)
        if not normalized:
            raise ValidationError("include_type must be one of: definitions, implementations, macros, testclasses")
        return normalized

    def _include_type_from_source_part(self, source_part: str) -> str | None:
        if source_part == "source/main":
            return None
        if source_part.startswith("includes/"):
            return self._normalize_include_type(source_part.rsplit("/", 1)[-1])
        return None

    def _build_read_hint(
        self, object_type: str, name: str, scope: str | None, include_type: str | None, uri: str | None = None
    ) -> str:
        if uri:
            return f'use abap_read_source(uri="{uri}")'
        if scope == "include" and include_type:
            return (
                f'use abap_read_source(object_type="{object_type}", name="{name}", '
                f'scope="include", include_type="{include_type}")'
            )
        if scope == "with_includes":
            return f'use abap_read_source(object_type="{object_type}", name="{name}", scope="with_includes")'
        return f'use abap_read_source(object_type="{object_type}", name="{name}", scope="main")'

    def _augment_update_error(self, error: SapBackendError, target: SourceTarget) -> SapBackendError:
        details = dict(error.details)
        details["target_uri"] = target.uri
        details["expected_etag_scope"] = "main" if not target.include_type else f"include:{target.include_type}"
        details["read_hint"] = self._build_read_hint(target.object_type, target.name, target.scope, target.include_type, target.uri)
        message = (
            f"{error} target_uri={target.uri} expected_etag_scope={details['expected_etag_scope']} "
            f"read_hint={details['read_hint']}"
        )
        return SapBackendError(message, details=details)

    def _object_path(self, object_type: str, name: str) -> str:
        registration = self._path_registration(
            object_type,
            "Writable types are class, interface, ddls/cds, dcls/dcl, bdef, ddlx, srvd, srvb, tabl, dtel, doma, devc, prog, fugr, and func",
        )
        return self._path_root(registration, name)

    def _read_path(self, object_type: str, name: str) -> tuple[str, str]:
        registration = self._path_registration(
            object_type,
            "Supported read types are class, interface, ddls/cds, dcls/dcl, bdef, ddlx, srvd, tabl, dtel, doma, devc, srvb, prog, fugr, and func",
        )
        root = self._path_root(registration, name)
        if registration.oo_source:
            source_part = self._oo_source_part(object_type)
            if source_part == "metadata":
                return root, "metadata"
            if source_part == "texts":
                if not registration.texts_template:
                    raise ValidationError(f"{registration.display_name} text elements are not registered")
                return registration.texts_template.format(name=quote(name.lower())), "metadata"
            return self._join_path(root, source_part), "source"
        return self._join_path(root, registration.read_suffix), registration.read_kind

    def _is_oo_source_type(self, object_type: str) -> bool:
        registration = self._find_path_registration(object_type)
        return bool(registration and registration.oo_source)

    def _is_source_search_type(self, object_type: str) -> bool:
        registration = self._find_path_registration(object_type)
        return bool(registration and registration.source_search)

    def _find_path_registration(self, object_type: str) -> AdtPathRegistration | None:
        normalized_type = object_type.lower()
        return ADT_PATH_REGISTRY_BY_ALIAS.get(normalized_type) or ADT_PATH_REGISTRY_BY_ALIAS.get(
            normalized_type.split("/", 1)[0]
        )

    def _path_registration(self, object_type: str, unsupported_message: str) -> AdtPathRegistration:
        registration = self._find_path_registration(object_type)
        if not registration:
            raise ValidationError(unsupported_message)
        return registration

    def _path_root(self, registration: AdtPathRegistration, name: str) -> str:
        if registration.canonical_type == "FUNC":
            group_name, function_name = self._function_module_parts(name)
            return registration.root_template.format(
                group_name=quote(group_name.lower()),
                function_name=quote(function_name.lower()),
            )
        return registration.root_template.format(name=quote(name.lower()))

    def _join_path(self, root: str, suffix: str | None) -> str:
        if not suffix:
            return root
        return f"{root.rstrip('/')}/{suffix.lstrip('/')}"

    def _collection_path(self, registration: AdtPathRegistration, name: str | None = None) -> str:
        if not registration.collection_template:
            raise ValidationError(f"{registration.display_name} does not define an ADT collection path")
        if registration.canonical_type == "FUNC":
            if not name:
                raise ValidationError("Function module collection paths require name in FUNCTION_GROUP/FUNCTION_MODULE format")
            group_name, _function_name = self._function_module_parts(name)
            return registration.collection_template.format(group_name=quote(group_name.lower()))
        return registration.collection_template

    def _initial_create_source(self, registration: AdtPathRegistration, name: str, description: str) -> str:
        if registration.canonical_type in {"PROG", "FUGR", "DTEL", "DOMA", "DEVC"}:
            return ""
        return self._default_source(registration.canonical_type, name, description)

    def _oo_source_part(self, object_type: str) -> str:
        parts = object_type.lower().split("/")
        if len(parts) < 2:
            return "source/main"
        requested = parts[-1].replace("-", "_")
        include_parts = {
            "main": "source/main",
            "source": "source/main",
            "definitions": "includes/definitions",
            "definition": "includes/definitions",
            "local_definitions": "includes/definitions",
            "implementations": "includes/implementations",
            "implementation": "includes/implementations",
            "local_implementations": "includes/implementations",
            "macros": "includes/macros",
            "testclasses": "includes/testclasses",
            "test_classes": "includes/testclasses",
            "tests": "includes/testclasses",
            "metadata": "metadata",
            "json": "metadata",
            "texts": "texts",
            "textelements": "texts",
            "text_elements": "texts",
        }
        return include_parts.get(requested, "source/main")

    def _adt_relative_url(self, base_path: str, href: str) -> str:
        if href.startswith("/"):
            return href
        return "/" + urljoin(base_path.lstrip("/"), href).lstrip("/")

    def _adt_api_path(self, uri: str) -> str:
        path = uri.strip()
        system_url = self.session.system_url.rstrip("/")
        if path.startswith(system_url):
            path = path[len(system_url) :]
        if not path.startswith("/sap/bc/adt/"):
            raise ValidationError("ADT run/result URI must start with /sap/bc/adt/")
        return path

    def _normalize_business_service_info_uri(self, path: str) -> str:
        if "?" in path:
            return path
        match = re.match(r"^(/sap/bc/adt/businessservices/odatav[24]/(?P<name>[^/?#]+))$", path, flags=re.IGNORECASE)
        if not match:
            return path
        return f"{match.group(1)}?servicename={quote(unquote(match.group('name')).upper())}"

    def _function_module_parts(self, name: str) -> tuple[str, str]:
        if "/" not in name:
            raise ValidationError("Function module source paths require name in FUNCTION_GROUP/FUNCTION_MODULE format")
        group_name, function_name = name.split("/", 1)
        if not group_name.strip() or not function_name.strip():
            raise ValidationError("Function module source paths require name in FUNCTION_GROUP/FUNCTION_MODULE format")
        return group_name.strip().upper(), function_name.strip().upper()

    def _is_metadata_write_path(self, path: str) -> bool:
        return not (path.endswith("/source/main") or "/includes/" in path)
