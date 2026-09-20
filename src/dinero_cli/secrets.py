"""Explicit protected-file credential backend; no automatic plaintext fallback."""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from dinero_cli.config import Settings, config_directory
from dinero_cli.errors import CLIError
from dinero_cli.personal import PersonalCredentials
from dinero_cli.storage import atomic_write, locked, read_private
from dinero_cli.windows import protect

WINDOWS = os.name == "nt"
WINDOWS_HEADER = b"dinero-dpapi-v1\n"


class SecretState(BaseModel):
    """Private credential record; sensitive fields are excluded from repr."""

    model_config = ConfigDict(extra="forbid")
    client_secret: SecretStr | None = Field(default=None, repr=False)
    tokens: dict[str, Any] | None = Field(default=None, repr=False)
    refresh_pending: bool = False
    personal: PersonalCredentials | None = Field(default=None, repr=False)

    def storage_bytes(self) -> bytes:
        """Serialize only for protected storage, never for a CLI response."""
        values = self.model_dump()
        if self.client_secret is not None:
            values["client_secret"] = self.client_secret.get_secret_value()
        if self.personal is not None:
            values["personal"] = self.personal.storage()
        raw = json.dumps(values, allow_nan=False).encode()
        return WINDOWS_HEADER + protect(raw) if WINDOWS else raw


@dataclass
class Transaction:
    """A credential record accessed only while its enclosing process lock is held."""

    path: Path
    state: SecretState = field(repr=False)

    def save(self) -> None:
        """Persist all credential fields atomically, or fail without claiming success."""
        atomic_write(self.path, self.state.storage_bytes())


class SecretStore:
    """Require explicit opt-in and serialize full token-rotation transactions."""

    def __init__(self, settings: Settings, directory: Path | None = None) -> None:
        if settings.credential_backend != "file":
            raise CLIError("Select protected storage with config set credential-backend file.")
        self.directory = directory or config_directory()

    @contextmanager
    def transaction(self, *, timeout: float = 10) -> Iterator[Transaction]:
        """Hold the lock across read, refresh and save; lock timeouts are visible failures."""
        with locked(self.directory, timeout=timeout):
            path = self.directory / "credentials.bin"
            try:
                raw = read_private(path)
            except FileNotFoundError:
                state = SecretState()
            else:
                if WINDOWS:
                    if not raw.startswith(WINDOWS_HEADER):
                        raise CLIError("Credential file is not Windows-protected data.")
                    raw = protect(raw[len(WINDOWS_HEADER) :], decrypt=True)
                try:
                    state = SecretState.model_validate_json(raw)
                except ValidationError as error:
                    raise CLIError(
                        "Stored credentials are invalid; restore or reauthorize."
                    ) from error
            yield Transaction(path, state)
