# Configuration and credential storage

`dinero config --help` lists all supported settings. Every leaf command accepts `--json`.
Public configuration and credentials are separate; config output never reads the credential
record. Setting a client secret does not contact Visma or grant authorization;
use [auth login](authentication.md) to authorize.

```sh
dinero config set organization 12345
dinero config get organization --json
dinero config list --json
dinero config set client-id YOUR_REGISTERED_PUBLIC_CLIENT_ID
dinero config set redirect-uri http://127.0.0.1:8765/callback
dinero config set response-mode form_post
dinero config set pkce true
dinero config set output human
```

Organization is a numeric ID, not an organization name or an automatically selected account.
Organization-dependent commands accept `--organization ID` for a single request.
`config set` changes exactly one saved field and reports the saved public value; `get` and
`list` show resolved values, so an environment override can differ from a saved value.

## Public settings and precedence

| Setting | Default | Environment override |
| --- | --- | --- |
| organization | Not set | DINERO_ORGANIZATION |
| client-id | Not set | DINERO_CLIENT_ID |
| redirect-uri | http://127.0.0.1:8765/callback (test); production uses registered HTTPS | DINERO_REDIRECT_URI |
| scopes | dineropublicapi:read dineropublicapi:write offline_access | DINERO_SCOPES |
| response-mode | form_post | DINERO_RESPONSE_MODE |
| pkce | true | DINERO_PKCE |
| output | human | DINERO_OUTPUT |
| api-base-url | https://api.dinero.dk:443 | DINERO_API_BASE_URL |
| trusted-api-origins | https://api.dinero.dk:443 | None; saved only |
| credential-backend | Not selected | DINERO_CREDENTIAL_BACKEND |

Explicit command options take precedence over environment values, then saved fields, then
built-in defaults. Invalid/empty supplied values fail rather than falling back. `--json`
forces machine output. Booleans in config are value-taking (`true`/`false`).
Config JSON keys use snake_case; setting arguments use kebab-case. Unknown settings and
secret fields are rejected. Values from the environment are never copied into saved config.

API origins must be HTTPS, with no userinfo, path prefix, query or fragment. They are normalized
to scheme, lowercase hostname and effective port. An API URL override cannot expand trust.
To deliberately authorize another origin, replace the comma-separated saved allowlist:

```sh
dinero config set trusted-api-origins https://api.dinero.dk,https://example.test:8443
```

This is a trust decision: list only servers permitted to receive bearer credentials. The
client must check the allowlist and token-origin binding before refresh or request (see the
CLI contract). All API commands use these shared checks.

## Local paths

By default `platformdirs` selects the user's local config directory: ordinarily
`~/.config/dinero-cli` on Linux and `%LOCALAPPDATA%\dinero-cli` on Windows. XDG_CONFIG_HOME is
honored on Linux. `DINERO_CONFIG_DIR` explicitly selects an isolated directory for automation
or tests. Use a local filesystem; network/shared filesystems are not a supported lock backend.

- `config.json`: non-secret saved settings.
- `credentials.bin`: private credential state, separate from public settings.
- `state.lock`: serializes config and credential transactions across processes.

Writes replace a flushed temporary file atomically. Existing POSIX state must belong to the
current user and have private permissions (directory 0700, files 0600); links and non-regular
files are rejected. Incorrect permissions fail rather than silently modifying other files.
Reads of missing public config return defaults without creating a directory.

## Explicit credential backend

Enable the protected-file backend before storing credentials:

```sh
dinero config set credential-backend file
dinero config set-client-secret --input /path/to/private-client-secret.txt --json
```

`--input -` reads one secret line from stdin, suitable for a password manager or CI secret
provider. Do not put the value in an argument, shell literal, command history or public log.
A trailing newline is removed. The command reports only `{"client_secret_stored": true}`.
On POSIX, a secret input file must also have private permissions; stdin needs no temporary file.
On Windows, protect any original plaintext input file with an appropriate user-only ACL or
supply it over stdin. It is not retained by the CLI.

Protection is platform-specific and is not silently substituted:

- **Linux:** the explicitly selected file backend uses private directory/file permissions.
  The contents are plaintext at rest; disk encryption is an operating-system decision. Root
  and processes running as the same user remain trusted. No keyring daemon or TUI is required.
- **Windows:** the credential payload is encrypted using current-user DPAPI with UI forbidden.
  Machine-wide encryption is never used. The same Windows identity/profile must be available
  to decrypt it; copying the file to another account or machine is not a portable credential
  bootstrap. DPAPI failure is a failure, never a plaintext fallback.

The process lock covers the whole credential transaction, including token refresh
and persistence of the replacement token. A competing command waits up to ten seconds and
then reports a clear busy error. See [authentication](authentication.md) for rotation and recovery.
A failed save never produces a successful storage response. Test credentials and state used
by the native build smoke tests live only in a temporary directory and are removed afterward.

## Removal and recovery

Removing/replacing the executable does not remove configuration or credentials. To remove
all local state, remove the application config directory deliberately after stopping running
commands. This does not revoke an authorization at Visma. Keep credential files out of source
control and ordinary support attachments; public diagnostics should use config output only.

References: [platformdirs](https://platformdirs.readthedocs.io/en/latest/api.html),
[filelock](https://py-filelock.readthedocs.io/en/latest/), and Microsoft's
[DPAPI protection](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)
and [unprotection](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata).
