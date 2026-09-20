---
name: dinero
description: Use the Dinero CLI to inspect and change Dinero accounting data, choose organizations, manage authorization, and run JSON API operations. Use the installed dinero executable as the tool interface.
---

# Dinero CLI

Use `dinero` (`dinero.exe` on Windows) as the deterministic interface. It owns OAuth,
credential storage, HTTP construction and execution. Do not replace it with curl,
handwritten HTTP requests, Python imports or reconstructed token exchanges.

## Discover the installed commands

Start with `dinero --version` and `dinero --help`; discover relevant groups and leaf
options with `dinero <group> --help` and `dinero <group> <command> --help`.

The current CLI has:

- `config list|get|set|set-client-secret`: local settings and protected secret input.
- `auth login|login-personal|status|logout`: user authorization and safe status metadata.
- `api get|post|put|delete PATH`: authenticated JSON API operations.

Dedicated organizations, contacts, products, invoices, purchase vouchers and entries
commands are planned, not yet available. Prefer dedicated resource commands when
the installed help lists them. Use `dinero api` only for an endpoint not represented
by a dedicated command. Do not guess paths, versions or payload schemas; use the
project's verified endpoint documentation for that operation. If its required schema
is unavailable, obtain it before issuing a write.

## Authentication and organization

Inspect `dinero auth status --json` before a workflow requiring API access. It reads
local metadata only; `authorized` does not prove server-side validity of access or refresh tokens.
For `auth login`, a configured client and initial Visma browser consent are required. Login uses the
user's registered Web application, exact redirect URI and permitted scopes; use
`offline_access` when the registration supports unattended refresh.

Use `dinero auth login --json` after configuration. For a headless host, inspect
`dinero auth login --help`: `--no-browser` requires `--authorization-url-file` pointing
to a private file. A registered production HTTPS callback also needs a new private
`--callback-file` delivered by the user's callback handler. Browser consent is still
required. Follow the authentication guide below; do not invent a callback service.

For personal integrations, use `auth login-personal --input FILE --json` instead: no Visma
app or browser callback is needed, but Dinero-approved personal client credentials, an
organization API key and a Pro/Total subscription are required. Supply a private UTF-8 JSON
object with `client_id`, `client_secret`, `api_key` and numeric-string `organization`, or pipe
it through `--input -` from an existing secret source. Do not create literal secrets in shell
history. Select the same organization in config or with `--organization`; a per-command
selection is not saved. Personal credentials are separate from the Visma client secret.

Only one authorization is active. Successful login switches method; a failed login preserves
previous state. Personal status includes `method` and `organization`; `refresh_available`
means the stored API key can renew the token, not that an OAuth refresh token exists.
Personal tokens renew automatically with a fresh API-key grant under a process lock.

Credentials must not appear in arguments, shell history, chat, JSON output or logs.
Supply an existing private client-secret file using
`dinero config set-client-secret --input /private/path/client-secret.txt`.
Never inspect or print the token store. The explicitly selected file backend uses
Windows DPAPI or Linux owner-only files; Linux files are not encrypted at rest.
`auth logout` removes local tokens and personal API credentials, preserves the separate Visma
client secret and does not revoke
server-side consent. Do not log out as routine cleanup of a read operation.

Visma authorization is user-based; personal authorization is bound to one organization.
Never select the first available organization implicitly:

```sh
dinero api get /v1/organizations --json
dinero config get organization --json
dinero config set organization 123 --json
```

Save a default only when requested. For a one-off operation, use `--organization ID`.
The API escape hatch replaces only `{organizationId}`; a path containing a literal ID
is unchanged by an override. Verify the effective target before any financial change.

## Read and process data

Use `--json` whenever inspecting or processing results. Success is one JSON document
on stdout, preserving the API shape. Errors are on stderr and exit nonzero. Default
output is for human reading; do not parse its tables.

```sh
dinero api get '/v1/{organizationId}/contacts' --organization 123 \
  --query page=0 --query pageSize=100 --json
```

Personal authorization rejects paths for another organization and ambiguous global routes;
its only organization-free route is read-only `/v1/organizations`.

Query options use exact API field names. Repeated `--query KEY=VALUE` pairs preserve
order and duplicate keys; supply plain text and let the CLI encode it. Do not put
query strings in PATH. Pagination is explicit; do not claim one page is all results.

## Writes and complex payloads

Book, send, delete, create and update require user authorization for the intended
operation and organization. A request to inspect data does not authorize a mutation.
Existing explicit authorization does not require repeated confirmation. If the target
or consequential action is unclear, clarify that missing scope before executing it.

Before an authorized write, read the relevant current resource and verify identity,
organization, payload and the latest API-required `Timestamp`/concurrency value.
Do not infer that creating a draft authorizes booking or sending it. Keep accounting
validation and business rules in Dinero; do not silently alter amounts, tax or dates.

Send a validated UTF-8 JSON object with original API field names and nested values:

```sh
dinero api post '/v1/{organizationId}/invoices' --organization 123 \
  --input invoice.json --json
cat invoice.json | dinero api post '/v1/{organizationId}/invoices' \
  --organization 123 --input - --json
```

These examples are mutations, not setup or discovery steps. Run them only for an
authorized request with the appropriate payload. In PowerShell prefer `--input
invoice.json`; pipes must emit UTF-8. GET has no body; multipart uploads, PDF/image
responses and file streaming are not supported by the JSON escape hatch.

## Handle failures

JSON errors have `error`, `status`, `message` and `details` on stderr. `status` is the
HTTP status or null. Preserve the exit code; do not turn an error or empty stdout
into an empty successful result. Empty successful responses are JSON `null`.

| Exit | Meaning / next action |
| --- | --- |
| 0 | Success; inspect the returned value. |
| 1 | Sanitized internal failure; report it. |
| 2 | Input/configuration failure; correct the stated input. |
| 3 | Authorization or HTTP 401; inspect status/context before login. |
| 4 | Other API error; inspect HTTP status and safe Dinero details. |
| 5 | Transport, storage, unsupported response or output failure. A write may have succeeded remotely. |
| 6 | HTTP 429; inspect `details.retry_after` when provided. |
| 130 | Interrupted operation; establish remote state before repeating a write. |

The CLI makes no automatic retries or redirects. After an uncertain write, read the
server state before considering another attempt; do not blindly resend, book or send
again. Honor rate limits and keep any subsequent attempt within the authorized scope.
A failed/uncertain Visma refresh requires fresh login rather than replaying an old refresh
token. Personal API keys are reusable; a failed grant still causes the current operation to
fail without an automatic retry. Personal integrations have a 60-request/minute limit.
Stop and report a provider failure when its cause cannot be corrected safely.

## Setup references

The skill is self-contained and can be copied or symlinked into any harness supporting
Markdown skills. Install the standalone binary separately; there is no official PyPI
package. The following project guides provide registration and endpoint details:

- [Binary installation](https://github.com/peterbb148/dinero-cli/blob/main/docs/installation.md)
- [Configuration](https://github.com/peterbb148/dinero-cli/blob/main/docs/configuration.md)
- [OAuth and headless bootstrap](https://github.com/peterbb148/dinero-cli/blob/main/docs/authentication.md)
- [Verified endpoint matrix](https://github.com/peterbb148/dinero-cli/blob/main/docs/api/endpoint-matrix.md)
- [JSON escape hatch](https://github.com/peterbb148/dinero-cli/blob/main/docs/api-command.md)
