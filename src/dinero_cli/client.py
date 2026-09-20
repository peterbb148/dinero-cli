"""One async Dinero request with explicit context, origin protection and no retries."""

import asyncio
import re
import ssl
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote, unquote, urlencode

import httpx

from dinero_cli.auth import AuthService
from dinero_cli.config import Settings, require_organization, require_trusted_origin
from dinero_cli.errors import CLIError
from dinero_cli.redaction import contains_known_secret, redact
from dinero_cli.serialization import decode_json

METHODS = frozenset({"GET", "POST", "PUT", "DELETE"})


def resource_path(path: str, settings: Settings) -> str:
    """Resolve only the documented organization placeholder and reject ambiguous routing."""
    if "{organizationId}" in path:
        path = path.replace("{organizationId}", quote(require_organization(settings), safe=""))
    if not path.startswith("/") or path.startswith("//") or "{" in path or "}" in path:
        raise CLIError("Use an API-root-relative path and only the {organizationId} placeholder.")
    if re.search(r"%(?![0-9a-fA-F]{2})", path):
        raise CLIError("API path has invalid percent encoding.")
    decoded = path
    while True:
        if (
            decoded.startswith("//")
            or any(char in decoded for char in "\\?#")
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in decoded)
            or any(segment in {".", ".."} for segment in decoded.split("/"))
        ):
            raise CLIError("API path must not contain queries, fragments, controls or traversal.")
        try:
            expanded = unquote(decoded, errors="strict")
        except UnicodeError as error:
            raise CLIError("API path has invalid UTF-8 encoding.") from error
        if expanded == decoded:
            return path
        decoded = expanded


def api_error(response: httpx.Response, secrets: tuple[str, ...]) -> CLIError:
    """Preserve status and safe response details, including a 429 Retry-After header."""
    try:
        value = decode_json(response.content) if response.content else None
    except (ValueError, UnicodeError):
        value = response.text
    safe = redact(value, secrets)
    message = f"Dinero API request failed (HTTP {response.status_code})."
    if isinstance(safe, str) and safe.strip():
        message = safe
    elif isinstance(safe, dict):
        for key in ("Message", "message", "title"):
            if isinstance(safe.get(key), str) and safe[key].strip():
                message = safe[key]
                break
    details: dict[str, Any] = {"response": safe}
    if response.status_code == 429 and "retry-after" in response.headers:
        details["retry_after"] = redact(response.headers["retry-after"], secrets)
    code = 3 if response.status_code == 401 else 6 if response.status_code == 429 else 4
    return CLIError(message, code=code, status=response.status_code, details=details)


class APIClient:
    """Share protocol handling across dedicated resources and the raw API escape hatch."""

    def __init__(
        self,
        settings: Settings,
        *,
        auth: AuthService | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.auth = auth if auth is not None else AuthService(settings)
        self.transport = transport

    async def request(
        self,
        method: str,
        path: str,
        *,
        query: Sequence[tuple[str, str]] = (),
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Send exactly one authenticated API operation; never replay an uncertain write."""
        origin = require_trusted_origin(self.settings)
        path = resource_path(path, self.settings)
        if method not in METHODS or (
            body is not None and (method == "GET" or not isinstance(body, dict))
        ):
            raise CLIError("Unsupported method or JSON body for this operation.")
        try:
            # Default system trust honours SSL_CERT_FILE/SSL_CERT_DIR for private CA testing.
            # No insecure switch or proxy/environment credential forwarding is supported.
            context = ssl.create_default_context()
            async with httpx.AsyncClient(
                transport=self.transport,
                verify=context,
                timeout=30,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                kwargs: dict[str, Any] = {"json": body} if body is not None else {}
                try:
                    # HTTPX QueryParams groups repeated keys and changes interleaved order.
                    # Encode the ordered pairs directly into the URL instead.
                    url = httpx.URL(origin + path)
                    if query:
                        url = url.copy_with(query=urlencode(query).encode("ascii"))
                    request = client.build_request(method, url, **kwargs)
                except (ValueError, UnicodeError, TypeError, httpx.InvalidURL) as error:
                    raise CLIError("Invalid path, query or JSON request payload.") from error
                destination = request.url
                expected = httpx.URL(origin)
                if (destination.scheme, destination.host, destination.port) != (
                    expected.scheme,
                    expected.host,
                    expected.port,
                ):
                    raise CLIError("Request destination differs from the configured API origin.")
                material = await asyncio.to_thread(self.auth.credentials)
                request.headers["Authorization"] = "Bearer " + material.access_token
                request.headers["Accept"] = "application/json"
                response = await client.send(request)
        except httpx.HTTPError as error:
            message = "API transport failed."
            if method != "GET":
                message += (
                    " The write result is uncertain; inspect server state before repeating it."
                )
            raise CLIError(message, code=5) from error
        except OSError as error:
            raise CLIError(
                "Unable to initialize TLS or access local credentials.", code=5
            ) from error
        if not response.is_success:
            raise api_error(response, material.redactions)
        if not response.content:
            return None
        try:
            value = decode_json(response.content)
        except (ValueError, UnicodeError) as error:
            raise CLIError(
                "API success response is not supported UTF-8 JSON.",
                code=5,
                status=response.status_code,
            ) from error
        # Preserve successful payloads, but refuse a response that echoes this authorization.
        # Credential output is never a supported way to inspect the active token/secret.
        if contains_known_secret(value, material.redactions):
            raise CLIError(
                "API response contains credential data and cannot be displayed.",
                code=5,
                status=response.status_code,
            )
        return value
