from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAP_MCP_", env_file=".env", extra="ignore")

    config_path: Path = Path("sap-mcp.yaml")
    auth_tokens: str | None = None


class ServerConfig(BaseModel):
    name: str = "SAP BTP Trial ABAP ADT MCP Server"
    auth_tokens: list[SecretStr] = Field(default_factory=list)


class AbapDevConfig(BaseModel):
    system_url: str | None = None
    sso_login_url: str | None = None
    callback_url: str = "http://localhost:8000/logon/success"
    reentrance_endpoint: str = "/sap/bc/sec/reentrance"
    reentrance_scenario: str = "FTO1"
    service_key_path: Path = Path("service-key.json")
    session_path: Path = Path(".sap-mcp-session.json")
    readable_packages: list[str] = Field(default_factory=lambda: ["*"])
    allowed_packages: list[str] = Field(default_factory=lambda: ["Z*"])
    allow_write: bool = False
    allow_activate: bool = False
    default_timeout_seconds: float = 30


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    abap_dev: AbapDevConfig = Field(default_factory=AbapDevConfig)


def _split_env_tokens(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [token.strip() for token in raw.split(",") if token.strip()]


def load_config(path: Path | None = None) -> AppConfig:
    settings = RuntimeSettings()
    config_path = path or settings.config_path
    data: dict[str, Any] = {}
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config = AppConfig.model_validate(data)

    env_tokens = _split_env_tokens(settings.auth_tokens)
    if env_tokens:
        config.server.auth_tokens = [SecretStr(token) for token in env_tokens]
    return config


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config()


def env_value(name: str | None, default: str | None = None) -> str | None:
    if not name:
        return default
    return os.getenv(name, default)
