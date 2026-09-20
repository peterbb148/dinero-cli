# Shared HTTP client

The async `APIClient` is the shared protocol service for all [dedicated resource commands](resources.md)
and the manual `dinero api` escape hatch. Agents use only the dedicated commands.
Commands supply the HTTP method, resource path, ordered query pairs and optional JSON object;
the service performs authentication, one HTTP operation and response/error translation.

- Supported methods are GET, POST, PUT and DELETE. GET cannot have a request body.
- Query pairs are URL-encoded once. Duplicate keys and order are retained.
- `{organizationId}` is the only path placeholder. It uses resolved organization context and
  fails before credential access if none is selected. Fully specified paths are unchanged.
- Paths are API-root-relative. Absolute/network URLs, query strings, fragments, backslashes,
  control/whitespace characters, malformed encoding and traversal (including encoded forms)
  are rejected. Use query parameters for filters and values containing spaces.
- The saved API-origin allowlist is checked before credential lookup. The constructed request's
  scheme/host/port is checked again before attaching a bearer token. Token records must match
  both the selected origin and client ID. Redirects are returned as HTTP errors, never followed.
- TLS certificate verification is always enabled. The API client uses the platform's default
  SSL trust, including explicitly configured `SSL_CERT_FILE`/`SSL_CERT_DIR` for private CAs.
  There is no insecure switch. Proxy variables are not used by the HTTP client.
- Connect/read/write/pool timeouts are each 30 seconds. Blocking credential transactions run in
  a worker thread, so the process lock does not block the async event loop.

## Responses and failures

Successful UTF-8 JSON retains its object/list/scalar shape. Empty successful bodies become null,
including empty 201 or 204 responses. Duplicate keys, non-finite numbers, invalid UTF-8 and
non-JSON successful responses fail with exit 5 rather than a fabricated JSON result. Request
bodies must be JSON objects; unsupported values fail before reading credentials or sending data.
Multipart upload, binary download and arbitrary headers are not implemented in this service.

A response that echoes an active credential is refused with exit 5 instead of displaying it.
Ordinary accounting data is otherwise returned unchanged. Error responses are sanitized for
access/refresh tokens, client secrets and other sensitive fields, including nested structures,
known values and common bearer/assignment forms in plain text. No headers or credentials are
logged. OAuth grant responses are handled separately by the [auth service](authentication.md).

API failures preserve HTTP status. A safe `Message`, `message`, `title` or plain-text body is used
as the diagnostic; the complete safe response is retained as `details.response`. Unknown error
shapes use a generic status message without discarding their safe details. HTTP 401 maps to exit 3,
429 to exit 6, and other failed statuses (including redirects/403/conflicts) to exit 4. HTTP 429
also retains a safe `Retry-After` value, when provided, as `details.retry_after`.

**No API request is automatically retried**, including reads and HTTP 429. This zero-retry policy
is deliberate: the caller can observe the error and decide when to retry. A transport error uses
exit 5; for POST/PUT/DELETE the diagnostic explicitly says the result is uncertain and instructs
the caller to inspect server state before repeating the write. A 401 does not trigger a hidden
refresh-and-replay of an operation; token refresh happens before the operation when needed.

Tests use HTTPX mock transports to verify method/path/body/query/headers, no redirects or retries,
status handling, secret redaction, and shape preservation. They perform no live bookkeeping.

Sources: [Dinero status/error codes](https://developer.dinero.dk/documentation/error-and-status/)
and [Dinero FAQ](https://developer.dinero.dk/documentation/faq/). The no-retry policy, error envelope
and exit mapping are CLI decisions defined in the [CLI contract](cli-contract.md).
