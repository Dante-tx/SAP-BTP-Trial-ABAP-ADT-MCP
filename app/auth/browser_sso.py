from __future__ import annotations

import json
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.config import AbapDevConfig
from app.errors import ConfigError, ValidationError


@dataclass(frozen=True)
class BrowserSession:
    system_url: str
    cookies: dict[str, str]
    headers: dict[str, str]
    reentrance: dict[str, str]
    created_at: float


class BrowserSsoSessionManager:
    def __init__(self, config: AbapDevConfig):
        self.config = config

    def login_url(self) -> str:
        if self.config.sso_login_url:
            return self.config.sso_login_url
        system_url = self.system_url().rstrip("/")
        sso_url = system_url.replace(".abap.", ".abap-web.")
        redirect_url = quote(self.config.callback_url, safe="")
        nonce = int(time.time() * 1000)
        endpoint = self.config.reentrance_endpoint
        separator = "&" if "?" in endpoint else "?"
        return (
            f"{sso_url}{endpoint}{separator}"
            f"scenario={quote(self.config.reentrance_scenario, safe='')}&redirect-url={redirect_url}&_={nonce}"
        )

    def open_login(self) -> dict[str, Any]:
        url = self.login_url()
        webbrowser.open(url)
        return {
            "login_url": url,
            "session_path": str(self.config.session_path),
            "next_step": "Complete SSO in the browser. The local callback will capture the ADT login result.",
        }

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
        data = json.loads(path.read_text(encoding="utf-8"))
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
        )

    def _write_session(self, session: BrowserSession) -> None:
        self.config.session_path.write_text(
            json.dumps(
                {
                    "system_url": session.system_url,
                    "cookies": session.cookies,
                    "headers": session.headers,
                    "reentrance": session.reentrance,
                    "created_at": session.created_at,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def system_url(self) -> str:
        if self.config.system_url:
            return self.config.system_url.rstrip("/")
        path = self.config.service_key_path
        if not path.exists():
            raise ConfigError(f"ABAP service key file not found: {path}")
        service_key = json.loads(path.read_text(encoding="utf-8-sig"))
        url = service_key.get("url") or service_key.get("endpoints", {}).get("abap")
        if not url:
            raise ConfigError("ABAP service key does not contain url or endpoints.abap")
        return str(url).rstrip("/")
