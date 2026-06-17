from __future__ import annotations

import json
import time
import webbrowser
from base64 import b64encode
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from pydantic import SecretStr

from sap_mcp.config import AbapDevConfig
from sap_mcp.errors import AuthorizationError, ConfigError, ValidationError


@dataclass(frozen=True)
class BrowserSession:
    system_url: str
    cookies: dict[str, str]
    headers: dict[str, str]
    reentrance: dict[str, str]
    created_at: float
    auth_mode: str = "sso"


class BrowserSsoSessionManager:
    def __init__(self, config: AbapDevConfig):
        self.config = config
        self._last_auto_login_opened_at = 0.0
        self._last_auto_login_url: str | None = None

    def login_url(self) -> str:
        if self.config.sso_login_url:
            return self.config.sso_login_url
        system_url = self.system_url().rstrip("/")
        sso_url = system_url.replace(".abap.", ".abap-web.")
        nonce = int(time.time() * 1000)
        endpoint = self.config.reentrance_endpoint
        separator = "&" if "?" in endpoint else "?"
        params = {"redirect-url": self.config.callback_url, "_": str(nonce)}
        if self.config.client:
            params["sap-client"] = self.config.client
        if self.config.reentrance_scenario:
            params["scenario"] = self.config.reentrance_scenario
        return (
            f"{sso_url}{endpoint}{separator}"
            f"{urlencode(params)}"
        )

    async def login(self) -> dict[str, Any]:
        if self.should_use_basic_auth():
            try:
                discovery = await self.validate_session(self.basic_auth_session())
            except (AuthorizationError, ConfigError) as exc:
                raise AuthorizationError(
                    "Basic ADT authentication failed. Check abap_dev.username/password "
                    "or legacy communication_user/communication_password, and confirm the SAP system allows Basic Auth for ADT."
                ) from exc
            return {
                **discovery,
                "reused_session": False,
                "authentication_required": False,
                "auth_mode": "basic",
            }

        try:
            session = self.load_session()
        except ConfigError:
            return self.open_login("missing_or_invalid_session")

        try:
            discovery = await self.validate_session(session)
        except (AuthorizationError, ConfigError):
            return self.open_login("expired_or_rejected_session")

        return {
            **discovery,
            "reused_session": True,
            "authentication_required": False,
            "session_path": str(self.config.session_path),
        }

    async def validate_session(self, session: BrowserSession | None = None) -> dict[str, Any]:
        from sap_mcp.connectors.adt import AdtConnector

        connector = AdtConnector(self.config, session or self.load_session())
        return await connector.discovery()

    def authenticated_session(self) -> BrowserSession:
        if self.should_use_basic_auth():
            return self.basic_auth_session()
        return self.load_session()

    def open_login(self, reason: str | None = None) -> dict[str, Any]:
        url = self.login_url()
        webbrowser.open(url)
        return {
            "authentication_required": True,
            "reused_session": False,
            "reason": reason or "manual_login",
            "login_url": url,
            "session_path": str(self.config.session_path),
            "next_step": "Complete SSO in the browser. The local callback will capture the ADT login result.",
        }

    def open_login_once(self, reason: str | None = None, *, cooldown_seconds: float = 120) -> dict[str, Any]:
        now = time.time()
        recently_opened = now - self._last_auto_login_opened_at < cooldown_seconds
        if recently_opened and self._last_auto_login_url:
            return {
                "authentication_required": True,
                "reused_session": False,
                "browser_opened": False,
                "reason": reason or "auto_login_required",
                "login_url": self._last_auto_login_url,
                "session_path": str(self.config.session_path),
                "next_step": "A SSO login page was already opened recently. Complete that login, then retry the tool.",
            }

        result = self.open_login(reason or "auto_login_required")
        self._last_auto_login_opened_at = now
        self._last_auto_login_url = result["login_url"]
        result["browser_opened"] = True
        return result

    def save_session(self, cookies: dict[str, str], headers: dict[str, str] | None = None) -> dict[str, Any]:
        if not cookies:
            raise ValidationError("At least one browser SSO cookie is required")
        safe_headers = headers or {}
        blocked = {"authorization", "cookie"}
        if any(key.lower() in blocked for key in safe_headers):
            raise ValidationError("Do not pass Authorization or Cookie headers; pass cookies separately")

        session = BrowserSession(
            system_url=self.system_url(),
            cookies=cookies,
            headers=safe_headers,
            reentrance={},
            created_at=time.time(),
        )
        self._write_session(session)
        return {"saved": True, "session_path": str(self.config.session_path), "cookie_count": len(cookies)}

    def save_cookie_header(self, cookie_header: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        cookies: dict[str, str] = {}
        for part in cookie_header.split(";"):
            name, separator, value = part.strip().partition("=")
            if separator and name:
                cookies[name] = value
        return self.save_session(cookies, headers)

    def save_reentrance_callback(self, params: dict[str, str], headers: dict[str, str] | None = None) -> dict[str, Any]:
        session = BrowserSession(
            system_url=self.system_url(),
            cookies={},
            headers=headers or {},
            reentrance=params,
            created_at=time.time(),
        )
        self._write_session(session)
        return {
            "saved": True,
            "session_path": str(self.config.session_path),
            "reentrance_fields": sorted(params),
            "next_step": "Run abap_adt_connect to validate whether the ADT login result is accepted.",
        }

    def load_session(self) -> BrowserSession:
        path = self.config.session_path
        if not path.exists():
            raise ConfigError("No local SSO session found. Run abap_adt_login and import cookies first.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Local SSO session file is not readable JSON: {path}") from exc
        cookies = data.get("cookies") or {}
        reentrance = data.get("reentrance") or {}
        if not isinstance(cookies, dict):
            cookies = {}
        if not isinstance(reentrance, dict):
            reentrance = {}
        if not cookies and not reentrance:
            raise ConfigError("Local SSO session file does not contain cookies or ADT reentrance callback data")
        headers = data.get("headers") or {}
        if not isinstance(headers, dict):
            headers = {}
        return BrowserSession(
            system_url=str(data.get("system_url") or self.system_url()),
            cookies={str(key): str(value) for key, value in cookies.items()},
            headers={str(key): str(value) for key, value in headers.items()},
            reentrance={str(key): str(value) for key, value in reentrance.items()},
            created_at=float(data.get("created_at") or 0),
            auth_mode=str(data.get("auth_mode") or "sso"),
        )

    def has_communication_user(self) -> bool:
        return self.has_basic_credentials()

    def has_basic_credentials(self) -> bool:
        return bool(self._basic_username() and self._basic_password())

    def should_use_basic_auth(self) -> bool:
        if self.config.auth_mode == "basic":
            return True
        if self.config.auth_mode == "auto":
            return self.has_basic_credentials()
        return False

    def communication_session(self) -> BrowserSession:
        return self.basic_auth_session()

    def basic_auth_session(self) -> BrowserSession:
        username = self._basic_username()
        password = self._basic_password()
        if not username or not password:
            raise ConfigError("Basic ADT credentials are not configured")
        raw = f"{username}:{password.get_secret_value()}"
        token = b64encode(raw.encode("utf-8")).decode("ascii")
        return BrowserSession(
            system_url=self.system_url(),
            cookies={},
            headers={"Authorization": f"Basic {token}"},
            reentrance={},
            created_at=time.time(),
            auth_mode="basic",
        )

    def _basic_username(self) -> str | None:
        return self.config.username or self.config.communication_user

    def _basic_password(self) -> SecretStr | None:
        return self.config.password or self.config.communication_password

    def _write_session(self, session: BrowserSession) -> None:
        self.config.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.session_path.write_text(
            json.dumps(
                {
                    "system_url": session.system_url,
                    "cookies": session.cookies,
                    "headers": session.headers,
                    "reentrance": session.reentrance,
                    "created_at": session.created_at,
                    "auth_mode": session.auth_mode,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def system_url(self) -> str:
        if self.config.system_url:
            return self.config.system_url.rstrip("/")
        raise ConfigError("ABAP system URL is not configured. Set abap_dev.system_url in sap-mcp.yaml.")
