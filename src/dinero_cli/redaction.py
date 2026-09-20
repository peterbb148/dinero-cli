"""Sanitize remote error data without logging it or changing successful accounting data."""

import re
from typing import Any
from urllib.parse import quote, quote_plus

SENSITIVE = {
    "authorization",
    "accesstoken",
    "refreshtoken",
    "clientsecret",
    "idtoken",
    "password",
    "codeverifier",
    "authorizationcode",
}
ASSIGNMENT = re.compile(
    r"(?i)\b(access[_-]?token|refresh[_-]?token|client[_-]?secret|id[_-]?token|password|"
    r"code[_-]?verifier|authorization[_-]?code)"
    r"""["']?\s*[:=]\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;&]+)"""
)
BEARER = re.compile(r"(?i)\bbearer\s+[^\s,;]+")


def redact(value: Any, secrets: tuple[str, ...]) -> Any:
    """Redact nested sensitive fields, bearer strings and known raw/URL-encoded values."""
    if isinstance(value, dict):
        return {
            redact(key, secrets): (
                "[REDACTED]"
                if re.sub(r"[^a-z]", "", key.lower()) in SENSITIVE
                else redact(item, secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        variants = {
            variant
            for secret in secrets
            if secret
            for variant in (secret, quote(secret, safe=""), quote_plus(secret))
        }
        for secret in sorted(variants, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        value = BEARER.sub("Bearer [REDACTED]", value)
        return ASSIGNMENT.sub(lambda match: match[1] + "=[REDACTED]", value)
    return value


def contains_known_secret(value: Any, secrets: tuple[str, ...]) -> bool:
    """Detect actual active credentials without treating ordinary accounting text as a secret."""
    if isinstance(value, dict):
        return any(contains_known_secret(part, secrets) for pair in value.items() for part in pair)
    if isinstance(value, list):
        return any(contains_known_secret(item, secrets) for item in value)
    if isinstance(value, str):
        return any(
            variant in value
            for secret in secrets
            if secret
            for variant in (secret, quote(secret, safe=""), quote_plus(secret))
        )
    return False
