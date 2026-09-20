# Dinero CLI Constitution

## Core Principles

### I. Thin API boundary (API-001)

The CLI MUST own authentication, HTTP, request construction and deterministic execution.
It MUST preserve Dinero resource names, payload fields, endpoint versions and response structure.
It MUST NOT reimplement Dinero business rules or invent uniform CRUD where the API differs.
Path parameters MUST be arguments, query parameters MUST be options, and complex bodies MUST
support JSON files and stdin. Prefer dedicated commands; `dinero api` is the escape hatch.

### II. Human-readable default output (OUT-001)

Every data command MUST provide a compact human-readable default: tables for records/lists and
labelled details where appropriate. Indented JSON alone is not the human presentation for an
object or list. Empty results MUST be understandable. Non-TTY use MUST NOT require interaction.
Tests MUST inspect actual output and meaningful fixture values, not merely the renderer name.

### III. Machine-readable JSON (OUT-002)

Every data command MUST accept the ASCII option `--json`. Successful JSON mode MUST write exactly
one valid JSON document to stdout, preserving the API response (including null/empty values).
It MUST NOT include headings, progress, diagnostic messages, ANSI escape codes or decorative text.
Success MUST exit 0. JSON MUST remain valid with redirected output and colour-related environment
variables. Control surfaces such as help/version have explicit, narrow contracts; they do not
create a general exemption for data commands.

### IV. Errors and secrets (ERR-001, SEC-001)

Errors MUST exit non-zero and write diagnostics to stderr, leaving stdout empty. In JSON mode,
stderr MUST contain exactly one object with `error: true`, `status`, `message` and `details`.
`status` is the preserved HTTP status when available, otherwise null. Exit codes MUST be stable.
Tokens, credentials and client secrets MUST NOT appear in either stream or logs. Test cases MUST
cover success and applicable validation, authentication, API and transport failures with sentinel
secrets. Review MUST verify logging and storage paths that output fixtures cannot exhaustively test.

### V. Discoverable and explicit execution (CMD-001, SAFE-001)

The real Typer command tree MUST be discovered recursively during contract checks. Every command
MUST have an exact registry entry and executable contract cases. Added, removed or renamed
commands and newly introduced group options MUST fail until their contract is updated.
Data commands MUST have tests of human output, JSON success and applicable failures. Classifying
an operation as control or no-data MUST include a concrete rationale and tests; reviewers MUST
reject classification that merely avoids JSON coverage.
Commands MUST be non-interactive when all required inputs are supplied. Organization-dependent
commands MUST permit explicit organization selection. Read commands MUST NOT mutate accounting
state. Book, send and delete MUST be explicit operations; ambiguous write failures MUST NOT be
blindly replayed. Mutation authorization and API fidelity remain review responsibilities.

### VI. Enforced quality and binary delivery (DEV-001, REL-001)

Use Python 3.12+, Typer and UV. Pre-commit MUST run Ruff lint, Ruff formatting and deterministic
command contract checks. The same checks MUST run in CI, alongside the full test/coverage suite.
New code MUST have measured coverage greater than 80%. Contract tests MUST make no live network,
provider or LLM calls. Test scenarios MUST isolate local configuration and replace API boundaries.
CLI distribution MUST use native Windows/Linux x86-64/ARM64 binaries, not an official PyPI release.
Only changed build inputs trigger a minor release; documentation and development tooling alone
MUST NOT. Retain binary assets for the latest two complete releases.

## Enforcement and Scope

| Rule | Automated evidence | Required review |
| --- | --- | --- |
| CMD-001 | Recursive discovery, exact registry matching, option inventory, negative tests | Honest command classification and complete help |
| OUT-001 | Actual human output, fixture content, non-TTY and empty/list/object cases | Readability and appropriate presentation |
| OUT-002 | Required option, strict JSON decoding, preserved payload, no ANSI/noise | Full API response fidelity beyond selected fixtures |
| ERR-001 | Expected exit status, empty stdout, structured stderr/error cases | Stable exit-code policy and completeness of applicable failures |
| SEC-001 | Sentinel secrets absent in streams; blocked network/subprocesses | Logs, persistence, permissions and secret lifecycle |
| API-001 | Relevant existing API/transport tests as commands are implemented | Endpoint fidelity and absence of replicated business rules |
| SAFE-001 | Mocked error/success cases, isolated configuration | Authorization, side effects and retry safety |
| DEV-001 | Pre-commit, Ruff, contract checker and measured coverage in CI | Required branch protection, Copilot review and workflow compliance |
| REL-001 | Release fingerprinting and binary matrix tests | Licensing and supported platform policy |

A passing contract suite proves only its enumerated cases. It MUST report the discovered command
count honestly, including zero data commands while only help/version exist. It MUST NOT assert
that all API operations or prose rules have been mechanically verified. The constitution is a
Spec Kit governance artifact; executable tests, not an LLM interpreting Markdown, enforce checks.

## Development Workflow

Follow the applicable AGENTS.md: inspect first, use an issue and approved plan, create a dedicated
issue branch, test, commit, push and open a PR. Never commit implementation directly to main.
Request Copilot review. Install local hooks with `uv run pre-commit install`; git clone does not
install them automatically. `uv run pre-commit run --all-files` runs the same checks on demand.
CI MUST run the hooks even if a local commit uses `--no-verify`; required-check enforcement is a
repository ruleset responsibility. Do not change global hooks or install harness-specific files.

## Governance

This constitution records project-wide requirements and MUST be read during specification,
planning, implementation and review. It does not replace explicit owner instructions or the
applicable AGENTS.md workflow. Amendments MUST be reviewed in a PR with rationale, version/date
updates, affected rule IDs and corresponding test/documentation changes. Removing or weakening
an automated check MUST be called out, never hidden in a registry exemption.

Constitution versions are independent of binary releases: MAJOR for incompatible rule removal or
redefinition, MINOR for added/materially expanded requirements, PATCH for clarifications.
This initial version ratifies the owner's existing CLI/output and pre-commit requirements.

**Version**: 1.0.0 | **Ratified**: 2026-09-20 | **Last Amended**: 2026-09-20
