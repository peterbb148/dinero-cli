"""Typed public configuration with explicit option/environment/file precedence."""

import json
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from platformdirs import user_config_path
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from dinero_cli.errors import CLIError
from dinero_cli.storage import atomic_write, locked, read_private


def https_origin(value: str) -> str:
    """Validate and normalize an HTTPS origin, including its effective port."""
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.path not in ("", "/")
        or url.query
        or url.fragment
        or any(char.isspace() for char in value)
        or "\\" in value
    ):
        raise ValueError("Expected an HTTPS origin")
    hostname = url.hostname.encode("idna").decode("ascii").lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    port = 443 if url.port is None else url.port
    if not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    return f"https://{hostname}:{port}"


class Settings(BaseModel):
    """Only public fields: credentials never belong in this schema."""

    model_config = ConfigDict(extra="forbid")
    organization: str | None = None
    client_id: str | None = None
    redirect_uri: str = "http://127.0.0.1:8765/callback"
    scopes: str = "dineropublicapi:read dineropublicapi:write offline_access"
    response_mode: Literal["form_post", "query"] = "form_post"
    pkce: bool = True
    output: Literal["human", "json"] = "human"
    api_base_url: str = "https://api.dinero.dk:443"
    trusted_api_origins: list[str] = Field(default_factory=lambda: ["https://api.dinero.dk:443"])
    credential_backend: Literal["file"] | None = None

    @field_validator("organization")
    @classmethod
    def organization_id(cls, value: str | None) -> str | None:
        """Organization IDs are opaque numeric strings, never an implicit first account."""
        if value is not None and (not value.isascii() or not value.isdigit()):
            raise ValueError("Organization must be a numeric ID")
        return value

    @field_validator("client_id", "scopes")
    @classmethod
    def nonempty(cls, value: str | None) -> str | None:
        """Reject explicit empty values and control characters."""
        if value is not None and (not value.strip() or any(ord(c) < 32 for c in value)):
            raise ValueError("Expected a nonempty value without control characters")
        return value

    @field_validator("api_base_url")
    @classmethod
    def api_origin(cls, value: str) -> str:
        """Validate URL syntax independently of the saved trust allowlist."""
        return https_origin(value)

    @field_validator("trusted_api_origins")
    @classmethod
    def trusted_origins(cls, value: list[str]) -> list[str]:
        """Use canonical exact origins, never wildcard trust."""
        if not value:
            raise ValueError("At least one trusted origin is required")
        return list(dict.fromkeys(https_origin(item) for item in value))

    @field_validator("redirect_uri")
    @classmethod
    def redirect(cls, value: str) -> str:
        """Accept a registered HTTPS handler or an explicit loopback test callback."""
        url = urlsplit(value)
        secure = url.scheme == "https" and bool(url.hostname)
        if secure:
            https_origin(f"https://{url.netloc}")
        loopback = url.scheme == "http" and url.hostname == "127.0.0.1" and bool(url.port)
        if (
            not (secure or loopback)
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or not url.path.startswith("/")
            or "\\" in value
            or any(char.isspace() for char in value)
        ):
            raise ValueError("Expected a registered HTTPS or http://127.0.0.1:PORT/PATH callback")
        return value


def config_directory() -> Path:
    """Resolve the application directory without modifying user state on reads."""
    override = os.environ.get("DINERO_CONFIG_DIR")
    if override is not None:
        if not override.strip():
            raise CLIError("DINERO_CONFIG_DIR must not be empty.")
        return Path(override).expanduser().absolute()
    return user_config_path("dinero-cli", appauthor=False, roaming=False)


def validate(values: dict[str, Any]) -> Settings:
    """Never render Pydantic errors containing input values or unknown secret keys."""
    try:
        return Settings.model_validate(values)
    except ValidationError as error:
        raise CLIError(
            "Invalid configuration. Use config --help for supported settings."
        ) from error


def saved_values(directory: Path | None = None) -> dict[str, Any]:
    """Load only explicit saved fields; absent files are the normal initial state."""
    path = (directory or config_directory()) / "config.json"
    try:
        raw = json.loads(read_private(path).decode("utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, UnicodeError) as error:
        raise CLIError("Configuration is not valid UTF-8 JSON.") from error
    if not isinstance(raw, dict):
        raise CLIError("Configuration must be a JSON object.")
    return validate(raw).model_dump(exclude_unset=True)


def load_settings(*, organization: str | None = None) -> Settings:
    """Apply public environment overrides, then explicit command options."""
    values = saved_values()
    for key in Settings.model_fields:
        if key == "trusted_api_origins":
            continue  # Trust can only be expanded through an explicit saved setting.
        variable = "DINERO_" + key.upper()
        if variable in os.environ:
            values[key] = os.environ[variable]
    if organization is not None:
        values["organization"] = organization
    return validate(values)


def require_organization(settings: Settings) -> str:
    """Reject a missing organization before a resource request is constructed."""
    if settings.organization is None:
        raise CLIError("Select an organization with --organization or config set organization.")
    return settings.organization


def require_trusted_origin(settings: Settings) -> str:
    """Reject origin overrides before any credential lookup or refresh."""
    if settings.api_base_url not in settings.trusted_api_origins:
        raise CLIError("API origin is not in the saved trusted-api-origins allowlist.")
    return settings.api_base_url


def setting_key(key: str) -> str:
    """Translate public kebab-case settings to model fields without echoing unknown input."""
    name = key.replace("-", "_")
    if name not in Settings.model_fields:
        raise CLIError("Unknown setting. Use config --help; secrets need set-client-secret.")
    return name


def save_setting(key: str, value: str) -> dict[str, Any]:
    """Validate and atomically save one public value without persisting environment overrides."""
    name = setting_key(key)
    parsed: Any = value
    if name == "trusted_api_origins":
        parsed = value.split(",")
    directory = config_directory()
    with locked(directory):
        values = saved_values(directory)
        values[name] = parsed
        validated = validate(values).model_dump(exclude_unset=True)
        atomic_write(directory / "config.json", (json.dumps(validated, indent=2) + "\n").encode())
    return {name: validated[name]}
