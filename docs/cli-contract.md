# CLI contract 1.0

Status: implementation specification, ratified 2026-09-20 for issue #1. The executable
currently exposes configuration commands and help/version/completion; this document does not
claim the planned API/auth commands exist. The [constitution](../.specify/memory/constitution.md)
governs enforcement.
The [endpoint matrix](api/endpoint-matrix.md) specifies the planned dedicated API operations.

## Commands and input

Use `dinero <resource> <verb> [path-arguments] [options]`. Commands are discoverable through
`--help` at every level. Path values are positional except organization context, which is
selected through `--organization ID` or saved configuration. Organizations list and local
config/auth operations do not require a selected organization. Missing context fails before
an API request. No fuzzy organization selection or automatic selection of the first account.

Setting precedence is: explicit command option > corresponding `DINERO_*` environment
variable > saved config > built-in default. Unset values do not override lower layers; an
explicit empty/invalid value is an error, not a fallback. For organization this is
`--organization` > `DINERO_ORGANIZATION` > saved `organization`; there is no built-in default.
`--json` selects JSON regardless of environment/saved output preference. Reads expose resolved
non-secret configuration; config writes change only the named saved field, never persist the
environment as a side effect. Trust allowlists are an exception: only explicit saved config
changes can extend them, never an environment override.

Query options preserve Dinero names on the wire. JSON keys and response field casing remain
unchanged. Domain terms such as ContactGuid, Voucher, Entry and Invoice are not translated.
CLI names use lower-case kebab-case. No local accounting/tax/payment business logic is added.

Every data command accepts `--json` on that command, including local auth/config status.
Options are supplied on the command that owns them; root-level `--json` is not promised.
`--help` and `--version` are control output and do not require credentials or network.
No normal command requires a TUI or confirmation prompt. A mutating verb is an explicit
operation; human/agent authorization must cover it. Help identifies create/update/delete,
book/send and raw post/put/delete as changes. Do not silently book or send a draft.

### JSON request payloads

`--input FILE` reads UTF-8 JSON, and `--input -` reads stdin. A request payload must be a JSON
object. Reject invalid UTF-8, invalid JSON, duplicate object keys and non-finite numbers before
network activity. Preserve unknown fields so new API fields do not require a CLI release;
validate known structural requirements without reproducing Dinero business rules.

Convenience body options include only explicitly supplied values; option defaults do not
materialize into request fields. Combine input and options at the top level only. If an
explicit option names a key already in the JSON object, fail with input exit code 2, even
if the values are equal. There is no implicit override or recursive merge. Nested objects
and line arrays are provided as JSON. No automatic GET/merge/PUT occurs for an update.

Version-sensitive writes use the exact Timestamp obtained by a prior explicit read. Keep it
as an opaque string. Never auto-fetch or refresh a timestamp during a write, and never retry
a conflicting or ambiguous mutation. Dinero determines which drafts/states can be changed.

## Output and errors

Human mode renders compact tables or labelled details. Empty lists report no results, empty
successful bodies report completion, and non-TTY output remains readable. Merely indenting
JSON is not human mode. Do not truncate data without an explicit indication in human mode.

JSON success is exactly one JSON document and a newline on stdout, exit 0, with the API
response shape preserved: arrays remain arrays, objects remain objects and scalars remain
scalars. An empty successful HTTP body (including 204) is represented as JSON `null`.
No status envelope, progress, ANSI escapes or informational messages share stdout.
Local commands return documented non-secret objects, rather than claiming an API response.

Errors leave stdout empty. Human diagnostics go to stderr. With `--json`, stderr contains
exactly one object and a newline:

```json
{"error": true, "status": 400, "message": "API error description", "details": {}}
```

`status` is the HTTP status when there was an HTTP response; otherwise it is null. `message`
is a useful non-secret diagnostic; `details` preserves safe structured API error information
(or is an empty object for local errors). JSON parser/argument/config/auth/transport failures
follow this contract too, including missing arguments and unknown options when `--json` was
supplied. A broken output pipe exits quietly with a nonzero transport/output code.

| Exit | Meaning |
| --- | --- |
| 0 | Success, including help/version |
| 1 | Unexpected internal failure; sanitized diagnostic, no traceback or secrets |
| 2 | Arguments, JSON input or configuration invalid/missing |
| 3 | Missing/expired authorization, token grant failure, or API HTTP 401 |
| 4 | API HTTP failure other than 401/429; includes 403 and conflicts |
| 5 | Transport, unsupported response format, or output I/O failure |
| 6 | HTTP 429 rate limit |
| 130 | User interruption |

Never print credentials, authorization codes, client secrets or access/refresh tokens in
success, error, config, debug output or logs. Redact known secret values and sensitive fields
before rendering remote error data; this security rule takes precedence over error-detail
fidelity. Successful accounting data otherwise remains unmodified. Do not echo an invalid
secret argument or dump a raw OAuth response. Secrets are never required as CLI arguments.

## Deterministic HTTP and escape hatch

`dinero api get|post|put|delete PATH` uses the same auth, config, organization resolution,
HTTP client and output boundary as dedicated commands. It accepts `--json`, `--organization`,
`--query KEY=VALUE` repeatedly and `--input FILE|-` on body-capable methods. Split a query
pair at the first equals sign; preserve duplicates/order and URL-encode keys/values exactly
once. GET has no `--input`. The method is explicit and mutation help is labelled accordingly.

PATH is an API-root-relative path beginning with `/`, optionally containing the exact
`{organizationId}` placeholder. Replace only that placeholder with an encoded selected
organization. A fully specified path is unchanged; organization override affects only a
placeholder. Reject unsupported placeholders, absolute/network-path URLs, fragments,
embedded credentials, backslashes and traversal. Supply query parameters through --query,
not an embedded query string. No arbitrary auth/header override is offered.

Default origin is `https://api.dinero.dk`. Base URLs and trusted origins require HTTPS with
a hostname and valid port, no userinfo, query or fragment; the base is an origin (no path
prefix). TLS certificate verification is always enabled. The saved trusted-origin allowlist
initially contains only `https://api.dinero.dk:443`. A different origin requires an explicit
saved allowlist addition before any authenticated request; changing the base URL or its
environment override alone never authorizes bearer forwarding. Normalize scheme/hostname
and effective port for comparison. Record the authorized API origin with tokens; changing
it requires new authorization, rather than forwarding an existing token to the new host.
Reject origins outside the allowlist before token refresh or request construction.
Follow no redirects with credentials. Use explicit timeouts. One
command sends one API operation, apart from necessary token refresh. Initially no automatic
HTTP retries, including on 429, are performed: return exit 6 and safely expose Retry-After
when present. Any future bounded retry policy must be explicit and must not replay writes.
A timeout/disconnection after a mutation is an uncertain result: inspect server state before
repeating it. Do not report a failed local token save as a successful login/refresh.

The initial escape hatch supports JSON requests and JSON or empty responses only. Invalid
JSON/non-JSON success fails clearly with exit 5; it is not wrapped as fake JSON success.
Multipart/file upload, binary downloads and custom headers require an explicit future
extension. API availability on day one does not imply every media type is supported.

## Shared implementation boundaries

Commands assemble arguments and call services; they do not own token storage or HTTP sessions.
Config provides typed, non-secret settings and deterministic option/environment/file precedence.
Auth owns browser/redirect flow, token exchange and process-safe token rotation through a secret
store. The async HTTP client owns origin validation, authenticated requests, status translation
and timeouts. Output owns human rendering, JSON serialization and sanitized common errors.
Tests replace network/auth boundaries and run the actual CLI parser and command callbacks.

Use these boundaries while implementing #2–#7; avoid empty placeholder service implementations.
Credentials and live Dinero consent are external prerequisites for opt-in live tests, not CI.
Live bookkeeping is never part of automated tests or initial setup.

## Sources and change policy

- [Dinero OpenAPI](https://api.dinero.dk/openapi/v1/swagger.json), fetched 2026-09-20;
  source checksum is recorded with the endpoint extraction.
- [Dinero authorization](https://developer.dinero.dk/documentation/authorization/): Visma
  user authorization, form-post callback, URL-encoded token exchange and offline_access.
- [Constitution](../.specify/memory/constitution.md): output, safety and governance requirements.

Exit codes, payload collision policy, command names and chosen endpoint versions are CLI
contract decisions. Review changes in a PR, update this version and the command-contract tests;
do not silently reinterpret established scripting behavior.
