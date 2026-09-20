"""Read strict JSON request objects without echoing their potentially sensitive content."""

import sys
from pathlib import Path
from typing import Any

from dinero_cli.errors import CLIError
from dinero_cli.serialization import decode_json


def read_object(input_file: str) -> dict[str, Any]:
    """Read a UTF-8 JSON object from a file or raw stdin; I/O errors remain explicit."""
    raw = sys.stdin.buffer.read() if input_file == "-" else Path(input_file).read_bytes()
    try:
        value = decode_json(raw)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise CLIError(
            "Input must be valid UTF-8 JSON with unique keys and finite numbers."
        ) from error
    if not isinstance(value, dict):
        raise CLIError("Input payload must be a JSON object.")
    return value
