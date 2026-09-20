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
- `organizations list`: discover accessible organizations.
- `contacts list|get|create|update|delete`: contact operations.
- `products list|get|create|update|delete`: product operations.
- `entries list|changes`: accounting entries and changes with explicit date filters.
- `accounts entry|purchase|deposit`: account views with endpoint-specific filters.
- `accounting-years list` and `vat-types list`: accounting lookup data.
- `files list`: one page of document archive metadata.
- `invoices list|get|create|update|delete|book|send`: explicit invoice operations.
- `purchase-vouchers get|create|update|delete|book`: explicit purchase voucher operations.

Agents must use dedicated resource commands. Do not use `dinero api`, curl, handwritten HTTP
or Python imports to access accounting data. If the needed operation has no dedicated command,
report the missing capability and implement it through the repository workflow before using it.
The executable retains an escape hatch for manual use; it is not an agent workflow.

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
The provider's `refresh_token` field is ignored for personal login, including empty values.

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
dinero organizations list --json
dinero config get organization --json
dinero config set organization 123 --json
```

Save a default only when requested. For a one-off operation, use `--organization ID`.
Dedicated resource commands resolve their path from the selected organization. Verify the
effective target before any financial change. Organization discovery also works with personal
authorization when no default organization is set; tokens remain bound to their organization.

## Read and process data

Use `--json` whenever inspecting or processing results. Success is one JSON document
on stdout, preserving the API shape. Errors are on stderr and exit nonzero. Default
output is for human reading; do not parse its tables.

```sh
dinero contacts list --organization 123 --page 0 --page-size 100 --json
```

Personal authorization rejects paths for another organization and ambiguous global routes;
its only organization-free route is read-only `/v1/organizations`.

Use documented kebab-case query options such as `--query-filter`, `--changes-since`, `--fields`,
`--page` and `--page-size`. Omitted values preserve API defaults. Pagination is explicit; one
list invocation reads one page only. `--deleted-only` and `--no-deleted-only` send true and false;
using both is an error. Products also support `--free-text-search`.

## Entries, accounts and document archive

Use explicit periods for accounting questions; do not invent a default financial year.

```sh
dinero entries list --organization 123 --from-date 2026-01-01 --to-date 2026-09-20 --no-include-primo --json
dinero accounts entry --organization 123 --fields AccountNumber,Name,VatCode,Category,IsHidden --json
dinero files list --organization 123 --file-status Unused --page 0 --page-size 1000 --json
```

`entries changes` takes `--changes-from`/`--changes-to`. Entry dates accept ISO dates/times and
are sent unchanged; `--include-primo` and `--no-include-primo` are mutually exclusive. No entries,
account, accounting-year or VAT-type operation has pagination/query-filter options. Account
views accept `--fields`; only `accounts entry` accepts `--category-filter`.
Files support comma-separated `--extensions`, `--uploaded-before`/`--uploaded-after` in
YYYY/MM/DD format, and `--file-status All|Used|Unused`. One page is not necessarily all files.
Unused files are unlinked documents, not a verified count of expenses: duplicates and non-booking
documents may be included. File commands return metadata only; binary downloads are not available.

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
dinero contacts create --organization 123 --input contact.json --json
cat product.json | dinero products create --organization 123 --input - --json
```

These examples mutate data and require authorization. Contact create/update require `Name`,
`CountryKey`, `IsPerson`, `IsMember`, `UseCvr`. Product create/update require `BaseAmountValue`,
`Quantity`, `AccountNumber`, `Unit`. Supply fields in JSON or supported options; no business
defaults are invented. Contact booleans use explicit positive/negative flags, for example
`--no-is-person --no-is-member --no-use-cvr`. `--name` and `--email` are available for contacts.
A field present in both JSON and an option is an error, even when values match. Unknown JSON
fields are retained for the API. Updates require the full documented payload and never merge
with a hidden read. Get/update/delete take a resource GUID argument; delete is destructive.
In PowerShell prefer file input; piped input must be UTF-8.

## Invoices and purchase vouchers

Invoice lists expose documented dates, fields, free text, status/query/change filters, sorting
and explicit pagination. Purchase vouchers have no documented list operation; discover linked
voucher GUIDs through reads such as entries and files. Do not invent `purchase-vouchers list`.

Use `invoices get GUID --json` or `purchase-vouchers get GUID --json` before an authorized change.
Pass the exact returned Timestamp in JSON or `--timestamp`; it is an opaque version identifier.
A conflict requires inspection and a new decision, never automatically replacing the timestamp.

Create/update take nested payloads through `--input FILE|-`, with optional top-level convenience
options shown in help. Invoice create requires `ProductLines`; update also requires `Timestamp`.
Each invoice line requires `AccountNumber`, `BaseAmountValue`, `Discount`, `Quantity`.
Purchase create requires `PurchaseType`; purchase update requires `ContactGuid`, `Lines`,
`PurchaseType`, `Timestamp`, `VoucherDate`. Each supplied purchase line requires `Amount`.
Dinero owns accounting rules, conditional requirements and defaults; do not invent them.

`create` only creates a draft. `book GUID --timestamp VALUE` books it and changes the accounts;
`--number` is optional. `invoices send GUID` sends email via the email endpoint; it does not book
or use EAN. Send requires explicit `ShouldAddTrustPilotEmailAsBcc` in JSON or one of
`--trustpilot-bcc` / `--no-trustpilot-bcc`.
Other email fields and Timestamp can be supplied in JSON or supported options; inspect the
intended recipient before authorized delivery. Delete sends its Timestamp object and is explicit
and destructive. No mutation chains, hidden reads, prompts or retries are performed.

For an already authorized booking (replace GUID and TIMESTAMP with values from a prior read):

```sh
dinero invoices book GUID --organization 123 --timestamp TIMESTAMP --json
```

All voucher writes support file/stdin input, preserve unknown fields and reject collisions with
explicit options. CLI help identifies required top-level payload fields and mutation consequences.

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
