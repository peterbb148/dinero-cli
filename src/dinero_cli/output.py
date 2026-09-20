"""Deterministic JSON and readable terminal output, with no global console state."""

import json
import sys
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from dinero_cli.errors import CLIError


def human_value(value: Any) -> str:
    """Render nested values as readable labels without interpreting Rich markup."""
    if value is None:
        return "Not set"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, dict):
        return "; ".join(f"{key}: {human_value(item)}" for key, item in value.items()) or "Empty"
    if isinstance(value, list):
        return "; ".join(human_value(item) for item in value) or "No results"
    return str(value).replace("\x1b", "\\x1b")


def emit(value: Any, *, json_mode: bool = False) -> None:
    """Write one JSON document or a complete, non-interactive human presentation."""
    if json_mode:
        print(json.dumps(value, ensure_ascii=False, allow_nan=False))
        return
    console = Console(file=sys.stdout, color_system=None, highlight=False, width=120)
    if isinstance(value, dict) and value:
        table = Table("Field", "Value", show_lines=False)
        for key, item in value.items():
            table.add_row(Text(str(key)), Text(human_value(item)))
        console.print(table)
    elif isinstance(value, list) and value:
        table = Table("#", "Value", show_lines=False)
        for index, item in enumerate(value, 1):
            table.add_row(str(index), Text(human_value(item)))
        console.print(table)
    else:
        console.print(Text("Completed" if value is None else human_value(value)))


def emit_error(error: CLIError, *, json_mode: bool) -> None:
    """Keep diagnostics exclusively on stderr."""
    if json_mode:
        print(json.dumps(error.payload(), ensure_ascii=False, allow_nan=False), file=sys.stderr)
    else:
        print(f"Error: {error.message}", file=sys.stderr)
