"""Deterministic JSON and readable terminal output, with no global console state."""

import io
import json
import os
import sys
from typing import Any, TextIO

from rich.console import Console
from rich.table import Table
from rich.text import Text

from dinero_cli.errors import CLIError


class OutputClosed(Exception):
    """Signal a closed output pipe without rendering another diagnostic into it."""


class PipeWriter:
    """Delegate text I/O while preventing renderers from substituting their own pipe exit code."""

    def __init__(self, stream: TextIO) -> None:
        self.stream = stream

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)

    def write(self, text: str) -> int:
        """Translate a broken pipe before Rich or Typer can handle it as exit 1."""
        try:
            return self.stream.write(text)
        except BrokenPipeError as error:
            silence_closed_pipe(self.stream)
            raise OutputClosed() from error

    def flush(self) -> None:
        """Apply the same policy to buffered output."""
        try:
            self.stream.flush()
        except BrokenPipeError as error:
            silence_closed_pipe(self.stream)
            raise OutputClosed() from error


def terminal_text(value: str) -> str:
    """Make terminal control bytes and isolated surrogates visible instead of executing them."""
    return "".join(
        json.dumps(char)[1:-1]
        if (ord(char) < 32 and char not in "\n\t")
        or 127 <= ord(char) < 160
        or 0xD800 <= ord(char) <= 0xDFFF
        else char
        for char in value
    )


def human_value(value: Any) -> str:
    """Render nested values as readable labels without interpreting Rich markup."""
    if value is None:
        return "Not set"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, dict):
        return (
            "; ".join(f"{human_value(key)}: {human_value(item)}" for key, item in value.items())
            or "Empty"
        )
    if isinstance(value, list):
        return "; ".join(human_value(item) for item in value) or "No results"
    return terminal_text(str(value))


def json_text(value: Any) -> str:
    """Serialize before any output, rejecting unsupported values without partial JSON."""
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
        text.encode("utf-8")
        return text
    except (TypeError, ValueError, RecursionError) as error:
        raise CLIError("Output cannot be represented as UTF-8 JSON.", code=5) from error


def emit(value: Any, *, json_mode: bool = False) -> None:
    """Write one JSON document or a complete, non-interactive human presentation."""
    if json_mode:
        print(json_text(value), flush=True)
        return
    console = Console(file=sys.stdout, color_system=None, highlight=False, width=120)
    if isinstance(value, dict) and value:
        table = Table("Field", "Value", show_lines=False)
        for key, item in value.items():
            table.add_row(Text(human_value(key)), Text(human_value(item)))
        console.print(table)
    elif isinstance(value, list) and value:
        table = Table("#", "Value", show_lines=False)
        for index, item in enumerate(value, 1):
            table.add_row(str(index), Text(human_value(item)))
        console.print(table)
    else:
        console.print(Text("Completed" if value is None else human_value(value)))
    sys.stdout.flush()


def emit_error(error: CLIError, *, json_mode: bool) -> None:
    """Keep diagnostics exclusively on stderr and escape untrusted terminal controls."""
    if json_mode:
        print(json_text(error.payload()), file=sys.stderr, flush=True)
    else:
        label = "Error" if error.status is None else f"Error (HTTP {error.status})"
        print(f"{label}: {terminal_text(error.message)}", file=sys.stderr, flush=True)
        if error.details:
            print(human_value(error.details), file=sys.stderr, flush=True)


def silence_closed_pipe(stream: TextIO) -> None:
    """Prevent Python's shutdown flush from printing a second broken-pipe traceback."""
    try:
        descriptor = stream.fileno()
    except (io.UnsupportedOperation, ValueError):
        return  # In-memory test streams have no OS descriptor or shutdown pipe flush.
    with open(os.devnull, "wb") as sink:
        os.dup2(sink.fileno(), descriptor)
