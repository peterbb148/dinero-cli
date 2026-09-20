# Dinero CLI

A Python/Typer CLI distributed as standalone Windows and Linux executables.
This milestone implements configuration, protected credential storage, Visma authorization and CD.
Dinero accounting API commands are not implemented yet; see the repository issues.
Start with [configuration](docs/configuration.md) and [authentication](docs/authentication.md).
There is no official pip/PyPI release. The project is source available under Apache-2.0 **subject to Commons Clause 1.0**;
see [LICENSE](LICENSE). It is not licensed under unrestricted Apache-2.0.

## Implementation contract

The planned CLI behavior is specified in [CLI contract](docs/cli-contract.md) and the
[verified endpoint matrix](docs/api/endpoint-matrix.md). These describe the implementation
target; use `dinero --help` to discover commands actually available in a binary.

## Development

Install UV, then run:

```sh
uv sync --locked
uv run dinero --help
uv run dinero --version
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov --cov-report=term-missing
uv sync --locked --group build
uv run python -m scripts.build build
```

## Builds and releases

- Every PR runs tests, lint, typing and measured coverage (minimum 81%). `PR gate`
  always completes, including documentation-only PRs. Set this as the required check.
- Binary smoke tests run only if the PR changes build inputs relative to its base.
- After merge, CD compares build inputs with the last successful managed release.
  Documentation alone creates no version, tag or binary. No commit-message convention,
  label or manual approval is required for a relevant change.
- Source/resources under `src/`, `assets/`, `packaging/`, the Python version, runtime/build
  dependencies and release/build tooling are inputs. README, docs, tests and lint-only
  configuration are not bundled. Dev-only lock updates do not trigger a release.
- The first binary version is `0.1.0`; subsequent releases increment minor and reset patch.
  The build version is injected into the workspace, never committed back to main.
- A draft reserves each release. Retry the failed CD run to resume it; do not delete its
  draft just to bypass a failure. A different pending release fails clearly instead of
  publishing out of order. Old runs cannot roll back a published descendant.
- Releases appear only after four native build/smoke jobs succeed. SHA256SUMS and
  GitHub provenance attestations identify the archives. Windows files are not code-signed.
- The latest two published managed releases retain binary assets; older tags and release
  notes remain. Only this workflow's named assets are removed. Temporary Actions
  transfers are deleted at run completion and also have one-day expiry.
- `workflow_dispatch` on main can recover a failed/retried run. It does not force a new
  release when inputs are unchanged. Concurrency queues up to GitHub's 100-run limit;
  overflow/cancelled runs require operator attention. No workflow commits to main.

| Binary | Native runner / tested baseline |
| --- | --- |
| Linux x86-64 | Ubuntu 24.04, glibc 2.39 |
| Linux ARM64 | Ubuntu 24.04 ARM, glibc 2.39 |
| Windows x86-64 | Windows Server 2022 |
| Windows ARM64 | Windows 11 ARM |

No 32-bit or musl/Alpine support is claimed. Extract the archive, place `dinero` or
`dinero.exe` on PATH (on Linux, `chmod +x dinero` if the unzip tool loses permissions),
and run `dinero --version`. No Python installation is required. Verify SHA256SUMS before
replacing an existing binary; keep the previous binary to roll back.

GHAS and repository rulesets/Copilot policy are separate
issues (#15, #16). Do not treat this workflow PR as completion of those controls.

## Constitution and command contracts

Read [.specify/memory/constitution.md](.specify/memory/constitution.md) before specifying,
implementing or reviewing a command. This is the standard GitHub Spec Kit constitution
location. No particular agent harness or Spec Kit installation is required.

Install this clone's hooks once (cloning does not install Git hooks):

```sh
uv run --locked pre-commit install
uv run --locked pre-commit run --all-files
uv run --locked pytest -q -s tests/contracts
```

Hooks run the locked Ruff lint/formatter and offline command contracts. Ruff may fix files;
review and stage those changes before retrying the commit. CI runs the same hooks and the
full test/coverage suite. Configure the required `PR gate` ruleset to enforce this at merge
(issue #16); local hooks alone cannot prevent bypass with `--no-verify`.

For each new command:

1. Add its exact command path to `REGISTRY` in `tests/contracts/test_cli.py`. Discovery
   visits all groups and leaves, and rejects missing/stale entries or changed options.
2. Classify it as data, control or group with a concrete rationale. Data commands require
   `--json`. Help/version/completion are narrow control surfaces; API responses are data.
3. Add `Case` fixtures with actual human-readable tokens, the unchanged expected JSON
   response, and expected exit codes. Cover meaningful empty and populated response shapes.
   Use each case's `setup` context manager to replace auth/transport at their boundaries.
4. Cover validation, authentication, API and transport errors where applicable. Record an
   explicit rationale for each inapplicable category in `excluded_failures`; all data
   commands require success and error cases. Include sentinel credentials when invoking
   `check` so accidental output disclosure fails.
5. Keep fixtures in `tests/contracts/`: its autouse fixture isolates configuration and
   blocks network/subprocess calls. No live Dinero account or LLM is used. JSON errors
   belong on stderr with empty stdout; use `status: null` if no HTTP response exists.

The checker exercises redirected human/JSON output with normal and forced-colour settings.
Its adversarial tests prove that missing `--json`, noise/ANSI, wrong streams/status,
changed payloads and unregistered commands fail. Today the CLI has **seven data commands** under `config` and `auth`;
help/version and Typer completion remain control surfaces. Completion callbacks run with shell
lookup/installation mocked. These tests do not prove visual quality, every possible secret
path, API fidelity or safe bookkeeping. The constitution maps those remaining obligations
to review. Governance, tests, hooks and development-only dependencies are not binary inputs.

## License and redistribution

Apache-2.0 with Commons Clause 1.0 permits use and modification, including internal
business use. It excludes selling a product or service whose value derives entirely
or substantially from this software, including relevant hosting/support fees.
A larger product with substantial independent value may still be sold. Read the
[complete terms](LICENSE) and [Commons Clause explanation](https://commonsclause.com/).
This is source available, not OSI open source. Third-party licenses remain independent;
no rights to Dinero/Visma services or trademarks are granted.

Every new native archive includes LICENSE, NOTICE, complete third-party notices,
SBOM.cdx.json (CycloneDX 1.6), and BUNDLE-MANIFEST.json. These identify actually frozen
Python distributions, the CPython runtime/build, the bootloader and the final executable
hash. The manifest records source/native input hashes without local absolute paths.
The runtime is an aggregate component, not a claim to a separately versioned SBOM for
every statically linked sublibrary. All upstream runtime notices are retained.

See [packaging/README.md](packaging/README.md) before changing Python or dependencies.
The older v0.1.0 archives predate this packaging; these new documents are not claimed
to be present in that release.
