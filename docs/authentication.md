# Visma Connect authorization

`dinero auth login`, `dinero auth login-personal`, `dinero auth status` and
`dinero auth logout` support human output and
`--json`. Visma authorization belongs to the user and can be used across organizations. Personal
authorization is bound to a single organization; see the personal integration section below. Login does
not choose an organization or send bookkeeping requests. API commands remain separate work.

## Register and configure your application

Dinero currently supports **Web** applications in Visma Connect. Register your own application;
the binary never contains a shared client secret. Configure the authorization-code grant, PKCE
if enabled (recommended), and the exact redirect URI, including case, path and port. Disable
OpenID Connect unless your integration separately implements it; this CLI requests only a code
and discards unused identity-token fields.

Apply for the Dinero read/write scopes and enable Offline Access when you need refresh tokens.
The defaults request `dineropublicapi:read dineropublicapi:write offline_access`. Only request
scopes your registration allows. Set `pkce false` only for a registration without PKCE.

```console
dinero config set client-id YOUR_REGISTERED_CLIENT_ID
dinero config set credential-backend file
dinero config set-client-secret --input /private/path/client-secret.txt
dinero config set response-mode form_post
dinero config set pkce true
```

See [configuration and secret storage](configuration.md) for private files, stdin secret input,
Windows DPAPI and Linux permissions. Secrets are never CLI arguments. `auth status --json`
returns only `authorized`, `access_token_valid`, `refresh_available`, `expires_at` (Unix seconds
or null), `configuration_matches` and `refresh_pending`. It makes no network calls and does not
refresh tokens. `authorized` means a local record exists, not that Visma has confirmed it is
still valid. No client secret, code, access token or refresh token appears in that output.

## Local test callback

Dinero documents localhost redirects for testing and asks that they be removed for production.
Register the exact local test callback, for example `http://127.0.0.1:8765/callback`, before use:

```console
dinero config set redirect-uri http://127.0.0.1:8765/callback
dinero auth login --json
```

The CLI binds only to `127.0.0.1`, opens the browser and accepts the registered `form_post` or
`query` response mode. It validates random state before exchanging the code and sends a PKCE
S256 challenge/verifier when configured. Nothing sensitive is returned in the callback page or
server logs. Wrong state, rejection, an occupied port, timeout or a failed token save is an
error. The default consent timeout is 300 seconds; `--timeout` accepts 1–1800 seconds.

## Production HTTPS callback and headless bootstrap

Use your own registered HTTPS callback handler for production. Configure its exact URL; the CLI
does not deploy a web server or manage that server's certificate. The handler must deliver the
original URL-encoded callback fields (`state` and `code`, or `state` and `error`) to a **new private
file** readable only by the CLI identity. For `form_post`, retain the raw form body; for `query`,
retain the raw query string without `?`. Write the complete file atomically, without logging the
callback parameters. Both the containing directory and file must be private on Linux.

Start login before completing browser consent:

```console
dinero config set redirect-uri https://YOUR_REGISTERED_HOST/oauth/callback
dinero auth login --no-browser \
  --authorization-url-file /private/path/consent-url.txt \
  --callback-file /private/path/new-callback.form --json
```

Open the consent link from the private URL file on a browser-equipped machine while the command
waits. Your handler delivers the callback file to the CLI host. For Windows use private paths in
the current user's profile. Do not paste authorization codes into shell commands, issue comments
or logs. Do not reuse a callback file: an existing file is rejected. Remove the temporary URL and
callback files after the attempt. The application client secret stays on the CLI host.

For local testing on a remote host, SSH port forwarding to the registered loopback port can be
used with `--no-browser --authorization-url-file`; no callback file is needed in that case.
`--no-browser` always requires a private URL file, keeping both output streams suitable for
scripts. The CLI does not print the consent URL. A browser must still perform initial Visma user
consent; headless does not mean consent is bypassed. No terminal UI or interactive prompt is used.

## Refresh, concurrency and logout

The shared auth service refreshes an access token that expires within 30 seconds when an API
caller requests it. Calls after initial login can run non-interactively. Refresh uses the same
configured client and saved API origin, independent of organization. An origin/client mismatch
requires login again; an untrusted API origin is rejected before looking up or refreshing tokens.

A process lock covers the entire read/exchange/save transaction. A durable `refresh_pending`
marker is written **before** exchanging a refresh token. New tokens are saved atomically before
being returned to an API caller. If the process crashes, the network result is uncertain, or a
post-exchange save fails, the next process refuses to replay the old refresh token: run login
again. This is intentional even with reusable refresh tokens. If the provider supplies a new
refresh token it replaces the old one; if it omits one, the existing token is retained as specified
by OAuth 2.0 section 6. Tokens are not refreshed by `auth status`.

OAuth grant failures use exit 3 and preserve any HTTP status without echoing the provider's raw
response. Transport/storage errors use exit 5; invalid local configuration uses exit 2. JSON
errors are a single envelope on stderr with empty stdout. No automatic grant retry is performed.

```console
dinero auth status --json
dinero auth logout --json
```

Logout clears local access/refresh tokens and any pending marker, preserving the client secret
and public settings. It **does not revoke** Visma's server-side authorization or tokens copied
elsewhere. Revoke the integration through Visma/Dinero when server-side revocation is required.
No live registration, production authorization or bookkeeping request is part of automated tests.

## Sources

- [Dinero registration requirements](https://developer.dinero.dk/documentation/getting-started/)
- [Dinero authorization](https://developer.dinero.dk/documentation/authorization/)
- [Visma web applications](https://docs.connect.visma.com/v1/docs/server-side-web-applications)
- [Visma offline access](https://docs.connect.visma.com/docs/offline-access)
- [OAuth 2.0 refresh-token rules, section 6](https://www.rfc-editor.org/rfc/rfc6749#section-6)

## Personal integration without a Visma app

For an integration used for your own company, Dinero also provides personal credentials.
This is a separate login method: it needs Dinero-approved client credentials and an API key
for the selected organization, but no Visma Connect app or browser callback. Apply under
Integrationer → Se og opret API-nøgler → Personlig integration. A Pro/Total subscription is
required. See [Dinero's personal integration guide](https://developer.dinero.dk/documentation/personal-integration/).

Prepare a private UTF-8 JSON object in an editor, replacing the placeholders with your
personal credentials (not the Visma application secret):

```json
{
  "client_id": "YOUR_PERSONAL_CLIENT_ID",
  "client_secret": "YOUR_PERSONAL_CLIENT_SECRET",
  "api_key": "YOUR_ORGANIZATION_API_KEY",
  "organization": "123"
}
```

Keep that input file private (0600 on Linux), outside the repository and logs. Supply its
path, never its contents, in command arguments. An upstream secret manager may alternatively
pipe the JSON bytes into `--input -`; never put literal secrets in a shell command.

```sh
dinero config set credential-backend file
dinero config set organization 123
dinero auth login-personal --input /private/path/personal.json --json
dinero auth status --json
dinero api get '/v1/{organizationId}/contacts' --json
```

`login-personal --organization 123` can override the default for that invocation, but does
not save a default: subsequent API calls must also select that organization. Status with
no matching saved/environment organization reports `configuration_matches: false`.
A personal status includes `method: "personal"` and `organization` in addition to the usual
safe fields. `refresh_available` means the stored API key can request a new grant; personal
integration has no OAuth refresh token. The provider's `refresh_token` response field is ignored,
including empty values. Status itself does not make a network request.

The CLI sends the documented Basic-authenticated, URL-encoded password grant to Dinero's
fixed HTTPS token endpoint. It saves the API key, personal client secret and returned access
token in the existing protected store, separately from the Visma client secret. Tokens are
bound to the personal client, explicit organization and configured API origin. Expiring
tokens are renewed with a new API-key grant under the process lock. No fallback to Visma,
redirect or hidden retry occurs. Unlike rotating Visma refresh tokens, the API key is reusable;
a failed exchange does not discard the previous authorization or mark a refresh token consumed.

Only one authorization is active. Successful `auth login` selects Visma and removes stored
personal credentials; successful `auth login-personal` replaces the active Visma token record.
A failed login preserves previous authorization. `auth logout` removes personal credentials
as well as tokens, while preserving the separate Visma client secret and public settings.
It does not revoke the organization's API key on Dinero's server. Remove the temporary input
file when it is no longer needed; do not display it for diagnostics.

API calls must select the bound organization, and explicit API paths for a different company
are rejected. Personal authorization supports organization-scoped `/vN/ID/...` endpoints and
read-only `/v1/organizations`; unknown/global escape-hatch routes are rejected until explicitly
supported, rather than forwarding an organization-scoped token to an ambiguous path.

Personal integrations have a documented limit of 60 requests/minute. HTTP 429 remains exit 6,
with a safe `retry_after` detail when supplied. Grant errors preserve HTTP status without
printing provider response bodies or secrets. No live account/API-key creation is performed
by this command; obtain approved credentials before use.
