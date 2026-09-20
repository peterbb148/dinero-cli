# Dinero CLI

A Python/Typer CLI distributed as standalone Windows and Linux executables.
This initial milestone implements the executable foundation and conditional CD.
Dinero API/authentication commands are not implemented yet; see the repository issues.
There is no official pip/PyPI release. The project license is awaiting the owner's choice
in issue #17; no open-source license is asserted by this PR.

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

GHAS, repository rulesets/Copilot policy, final licensing/notices and SBOM are separate
issues (#15, #16, #17). Do not treat this workflow PR as completion of those controls.
