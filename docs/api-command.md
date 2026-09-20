# JSON API escape hatch

`dinero api get|post|put|delete PATH` sends one request through the common authenticated
client. Discover exact syntax with `dinero api --help` and `dinero api post --help`.
Prefer a dedicated resource command when one exists. Use documented Dinero endpoints;
the CLI does not infer endpoint versions or validate accounting rules.

After [configuration](configuration.md) and [login](authentication.md):

```sh
dinero api get /v1/organizations --json
dinero config set organization 123
```

The raw command accepts API query names directly, rather than resource-specific options:

```sh
dinero api get '/v1/{organizationId}/contacts' \
  --query page=0 --query pageSize=100 --query 'queryFilter=Name eq "Acme"' --json
dinero api get '/v1/{organizationId}/contacts' --organization 456 --json
dinero api post '/v1/{organizationId}/contacts' --input contact.json --json
cat invoice.json | dinero api post '/v1/{organizationId}/invoices' --input - --json
```

PowerShell accepts the same quoted paths; to pipe a JSON file, use
`Get-Content -Raw -Encoding utf8 invoice.json | dinero api post '/v1/{organizationId}/invoices' --input - --json`.
Ensure the shell encodes piped bytes as UTF-8, or use `--input invoice.json` directly.

Each `--query KEY=VALUE` splits at the first equals sign. Keys must be nonempty; values
may be empty or contain further equals signs. Repeated keys and their original order are
preserved. Values are URL-encoded once, so provide ordinary text, not pre-encoded escapes.
Only the literal `{organizationId}` placeholder is replaced using `--organization`, then
environment/saved defaults. `/v1/123/contacts` remains organization 123 even with an override.
Organization-free endpoints need no default organization.

POST, PUT and DELETE change remote state and execute without confirmation. Read the
relevant resource first, verify the intended organization and retain any API-required
concurrency values. The CLI does not add reads, retries, bookkeeping logic or confirmation
prompts. DELETE is explicitly destructive. Inspect server state after an uncertain write
before deciding whether to repeat it.

`--input FILE` or `--input -` accepts a UTF-8 JSON object. Original field names and nested
values are preserved; duplicate keys, non-finite numbers and invalid Unicode are rejected
before authentication/network access. Without input, a write has no body. GET rejects
`--input`. No arbitrary headers, token command-line options or absolute URLs are accepted.
Paths cannot contain a query string, fragment, traversal or an alternate origin.

Default output is a readable table/detail view. `--json` (or configured JSON preference)
prints exactly the returned JSON value to stdout, including `null` for an empty response.
Errors appear only on stderr, with the [stable exit codes](cli-contract.md#output-and-errors).
HTTP status and safe Dinero details are preserved. A 429 response exits 6 and includes
`details.retry_after` when supplied by Dinero; no automatic retry occurs.

This escape hatch handles JSON endpoints only. It does not upload multipart data, download
PDFs/images or stream files. A nonempty successful response that is not UTF-8 JSON fails
with exit 5 and its HTTP status; raw response bytes are not printed or saved. These endpoints
need a future explicit file command. Authentication, origin checks, TLS and error redaction
are shared with the [HTTP client](http-client.md); redirects are never followed.
