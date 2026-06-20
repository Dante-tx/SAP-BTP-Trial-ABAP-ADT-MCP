from __future__ import annotations

import fnmatch

from sap_mcp.connectors.core.registry import DEFAULT_MAX_RESULTS
from sap_mcp.errors import AuthorizationError, ValidationError


class AdtAuthorizationMixin:
    def _assert_write_allowed(self, reason: str) -> None:
        if not self.config.allow_write:
            raise AuthorizationError("ABAP write access is disabled by configuration")
        if not reason.strip():
            raise ValidationError("Write reason is required")

    def _assert_package_allowed(self, package: str) -> None:
        if not self._is_package_write_allowed(package):
            raise AuthorizationError(f"Package {package} is not in the configured write allowlist")

    def _is_package_write_allowed(self, package: str) -> bool:
        package_upper = package.upper()
        if package_upper == "$TMP":
            return True
        return any(fnmatch.fnmatchcase(package_upper, pattern.upper()) for pattern in self.config.allowed_packages)

    def _assert_package_read_allowed(self, package: str) -> None:
        package_upper = package.upper()
        if not any(fnmatch.fnmatchcase(package_upper, pattern.upper()) for pattern in self.config.readable_packages):
            raise AuthorizationError(f"Package {package} is not in the configured read allowlist")

    async def _assert_object_write_allowed(self, object_type: str, name: str) -> None:
        package = await self._object_package(object_type, name)
        if not package:
            raise AuthorizationError(f"Cannot determine package for {object_type} {name}; write operation blocked")
        self._assert_package_allowed(package)

    async def _object_package(self, object_type: str, name: str) -> str | None:
        registration = self._find_path_registration(object_type)
        search_name = name
        if registration and registration.canonical_type == "FUNC":
            _group_name, search_name = self._function_module_parts(name)
        search_type = registration.search_type if registration else object_type.upper().split("/", 1)[0]
        try:
            results = await self._search_repository_objects(search_name, DEFAULT_MAX_RESULTS, search_type, None)
        except Exception:
            return None
        object_name = search_name.upper()
        for item in results:
            if item.get("name", "").upper() != object_name or not item.get("packageName"):
                continue
            if registration and registration.canonical_type == "FUNC" and "/" in name:
                resolved_name = self._match_registration_name(item.get("uri", ""), registration)
                if resolved_name and resolved_name != name.upper():
                    continue
                return item["packageName"]
            return item["packageName"]
        return None
