"""Shared, non-secret failures at the CLI boundary."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CLIError(Exception):
    """Carry a safe diagnostic, exit code and optional HTTP details."""

    message: str
    code: int = 2
    status: int | None = None
    details: Any = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        """Return the stable machine-readable error envelope."""
        return {
            "error": True,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }
