"""Strict JSON decoding shared by wire responses and future payload input commands."""

import json
import math
from typing import Any


def decode_json(raw: bytes) -> Any:
    """Require UTF-8 JSON with unique keys and finite numbers, preserving its shape."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def number(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("Non-finite JSON number")
        return parsed

    def constant(value: str) -> None:
        raise ValueError("Non-finite JSON constant")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_float=number,
            parse_constant=constant,
        )
    except RecursionError as error:
        raise ValueError("JSON nesting exceeds the decoder's supported depth") from error
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            item.encode("utf-8")  # JSON escape sequences must not introduce lone surrogates.
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return value
