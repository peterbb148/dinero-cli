# Release quality and optional live verification

Automated tests never use a real Dinero account. Run the configured development checks with UV:

```sh
uv sync --locked
uv run pre-commit run --all-files
uv run mypy
uv run pytest --cov --cov-report=term-missing --cov-report=xml
uv run diff-cover coverage.xml --compare-branch origin/main --fail-under 81
```

Total measured coverage must reach 81%; changed measured code must also reach 81%. Coverage is
not proof of correct accounting. Report the actual test count and measured percentages in each
implementation PR; do not copy an old number as evidence for a new commit.

## Automated evidence

| Boundary | Evidence |
| --- | --- |
| Every command: help, human rendering, JSON, stderr and stable exits | `tests/contracts`, discovered command registry; no network |
| Every dedicated resource: methods, versions, options, body, unknown fields, conflicts | `test_resources.py`, `test_reads.py`, `test_vouchers.py` |
| Visma grants, callback/state/PKCE, renewal, failed persistence | `test_auth.py`, `test_oauth_callback.py`; fake provider responses |
| Refresh serialization across four independent processes | `test_auth.py::test_parallel_processes_exchange_a_single_refresh_token`; one recorded exchange |
| Personal grant/renewal, organization binding, no silent auth fallback | `test_personal.py` |
| Credential redaction, URL/origin/redirect rejection, rate limits, uncertain writes | `test_client.py`, `test_api.py`, `test_output.py`, `test_secrets.py` |
| Real packaged process on every target | `scripts.build` → `scripts.smoke_api` → `scripts.smoke_resources` |
| Bundled dependencies/runtime, notices, SBOM, architecture | `scripts.build`, `scripts.notices`, their tests and archive manifest |

The four native jobs build Windows/Linux x86-64/ARM64 and run the executable outside the checkout
with an empty PATH. They use a private temporary config, fixed test credentials and a local HTTPS
server with certificate verification enabled. OpenSSL is a build-host fixture dependency, not a
runtime requirement. The runtime CLI has no test-mode switch or configurable OAuth token endpoint.

The native resource scenario covers every dedicated API leaf command. Body-capable operations
run with both literal UTF-8 file input and stdin. Captured requests must have the exact method,
versioned path, payload and bearer header. Each invocation must produce exactly one request:
no hidden reads, pagination, booking, sending or replay. A default organization of 123 remains
unchanged after explicit requests for 456. Local auth status performs no network call.

For invoice create/book/send/delete the fixture injects HTTP 409, HTTP 429 and a connection close
after receiving the request. Each failure must use the documented exit/status, keep JSON errors
on stderr, redact credentials, preserve rate-limit details and report uncertain writes. These
are synthetic operations; no invoice is sent and no real accounts are changed. The manual escape
hatch remains covered by the local fixture; this is a product test, not an agent accounting workflow.

Adversarial tests deliberately corrupt the fixture results and confirm that the smoke checker
fails. An inventory test fails when a new dedicated leaf lacks a native scenario. CI runs this
suite before building; all four native jobs must pass before release publication. Documentation-only
changes run test/security/review gates but do not build or create a release.

Reproduce a native build on a supported host (OpenSSL on the build-host PATH):

```sh
uv sync --locked --no-dev --group build
uv run --no-sync python -m scripts.build build
uv sync --locked
```

## Opt-in live smoke: an explicitly selected test company only

Live verification is separate and is never a default CI job or prerequisite for unit tests. It
requires a Dinero test company approved for the intended operations and your own credentials.
No production organization, customer contact, real recipient or production document may be reused
as a test fixture. Keep all credentials and accounting responses outside the repository and logs.

1. Verify the downloaded archive checksum/provenance and record `dinero --version` and platform.
2. Select a new private config directory with `DINERO_CONFIG_DIR`, isolating production state.
   In Bash use `export DINERO_CONFIG_DIR=/private/test-state`; in PowerShell use
   `$env:DINERO_CONFIG_DIR = 'C:\private\test-state'`. Supply private paths for the current user.
3. Configure the file credential backend and one method from [authentication](authentication.md).
   Visma requires a registered app, permitted scopes, matching callback and initial consent.
   Personal login requires approved personal credentials, a test-company API key and the provider's
   required subscription. Never copy production credentials into test state or put secrets in arguments.
4. Use `dinero auth status --json` and `dinero organizations list --json`. Verify the returned test
   company identity. Local status alone is not evidence of server-side authorization. Use explicit
   `--organization TEST_ID` for subsequent commands; replace TEST_ID with its numeric ID.
5. Perform only reads first:

```sh
dinero contacts list --organization TEST_ID --page 0 --page-size 1 --json
dinero products list --organization TEST_ID --page 0 --page-size 1 --json
dinero invoices list --organization TEST_ID --page 0 --page-size 1 --json
dinero accounts entry --organization TEST_ID --json
dinero accounting-years list --organization TEST_ID --json
dinero vat-types list --organization TEST_ID --json
dinero files list --organization TEST_ID --page 0 --page-size 1 --json
```

For entries, choose an actual test-company period with `entries list --from-date ... --to-date ...`.
For `entries changes`, select a deliberate `--changes-from`/`--changes-to` interval. Read purchase
vouchers only using a GUID discovered in test data; there is no purchase-voucher list operation.
Stop on provider failures; record sanitized exit/HTTP status rather than treating failures as an
empty result. Do not call `dinero api` or direct HTTP as an agent workaround.

### Financial mutations are a separate opt-in step

A read-smoke request does not authorize writes. Before any mutation, explicitly agree the test
company, fixture contact/document, full payload and intended create/update/book/send/delete scope.
Use dedicated commands and the current help. Read referenced contacts/accounts and verify the
payload; then an authorized create may submit a draft using `--input FILE --json`. Record its GUID
without exposing account data publicly. Read it back and use its current Timestamp for an authorized
update/book/delete. Creation does not imply booking or delivery. If email delivery is separately
approved, use only a controlled test recipient; never a real customer address.

A conflict or uncertain result stops the write sequence. Inspect server state before deciding
whether another explicitly authorized operation is needed. Do not automatically refresh Timestamp,
resend a write, or clean up with deletion. Cleanup itself requires appropriate scope and may not be
available after booking; leave such fixtures for the test-company owner to handle deliberately.

Record version/platform, test-company identifier privately, login method, commands/operations,
exit/status and outcome. State which scenarios were skipped. The automated suite proves local
protocol/packaging contracts; it does not prove live Visma consent, subscription permissions,
provider business validation, actual booking or email delivery. No such live financial scenario
is claimed by a green CI run. Remove private bootstrap files and deliberately log out of the
isolated test configuration when finished; never log out of production as test cleanup.
