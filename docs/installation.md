# Install and upgrade a standalone binary

Download the matching ZIP and `SHA256SUMS` from the
[latest complete GitHub release](https://github.com/peterbb148/dinero-cli/releases/latest).
No Python, UV or pip is required to run a release binary.

| Archive suffix | Supported / tested baseline |
| --- | --- |
| `linux-x86_64.zip` | Ubuntu 24.04 x86-64, glibc 2.39 |
| `linux-arm64.zip` | Ubuntu 24.04 AArch64, glibc 2.39 |
| `windows-x86_64.zip` | Windows Server 2022 x86-64 |
| `windows-arm64.zip` | Windows 11 ARM64 |

These are the supported baseline environments, not a claim that older OS releases work.
There is no 32-bit, macOS or musl/Alpine build. On Linux, `uname -m` reports `x86_64` or
`aarch64`. On Windows use Settings → System → About → System type; choose ARM64 for
an ARM machine, even when your current shell runs under x64 emulation.

The native CI runners match this matrix. PyInstaller bundles the interpreter, Python
modules and required native libraries into one executable. ELF/PE headers are checked
for the expected architecture, so an emulated x64 executable cannot pass as ARM64.
System libraries remain OS requirements; see the [packaging inventory](../packaging/README.md).
Windows executables are **not code-signed**. SHA-256 checksums check integrity, and GitHub
build provenance identifies the workflow/source; neither is a Windows publisher signature.

## Linux

In the download directory, verify the archive (GNU coreutils):

```sh
sha256sum --check --ignore-missing SHA256SUMS
```

Require an `OK` result for the archive you downloaded. Extract the entire archive to a
version-specific directory, retaining its license, SBOM and notices. For example, after
extracting it to `$HOME/.local/share/dinero/vX.Y.0/`:

```sh
chmod +x "$HOME/.local/share/dinero/vX.Y.0/dinero"
mkdir -p "$HOME/.local/bin"
ln -sfn "$HOME/.local/share/dinero/vX.Y.0/dinero" "$HOME/.local/bin/dinero"
export PATH="$HOME/.local/bin:$PATH"
dinero --version
dinero --help
```

Replace `vX.Y.0` with the downloaded version. Add the PATH export to your shell profile if
`~/.local/bin` is not already present. The downloaded executable must be runnable from its
temporary extraction location; a `noexec` temporary filesystem is not supported by this
one-file bundle.

## Windows

In PowerShell, run `Get-FileHash .\dinero-vX.Y.0-windows-arm64.zip -Algorithm SHA256`
(or the x86-64 archive) and compare its hash with that archive's line in `SHA256SUMS`.
Extract the whole ZIP to a version-specific directory, for example
`$env:LOCALAPPDATA\Programs\Dinero\vX.Y.0`. Keep the accompanying notices and SBOM.

Run the extracted `dinero.exe --version` and `dinero.exe --help`. Add its directory to your
user PATH using Environment Variables in Windows Settings, then open a new terminal.
The binary uses the user's Windows DPAPI identity for the configured file credential
backend; credentials copied from another account/machine are not portable.

## First use

Follow [configuration](configuration.md), then [Visma authorization](authentication.md).
Provide your own registered OAuth application; release binaries contain no shared client
secret. Inspect organizations with `dinero api get /v1/organizations --json`, then save the
chosen ID using `dinero config set organization ID`. See [API usage](api-command.md).

## Upgrade, rollback and uninstall

Verify and extract the new version into a separate directory, run `--version`, then update
the symlink/PATH to select it. Keep the previous local directory if you need rollback;
GitHub retains binary assets for only the latest two complete releases. Never overwrite
an executable while a process is running. Configuration and tokens live outside the
installation directory and are preserved when replacing or removing binaries.

To uninstall, optionally run `dinero auth logout` first to remove locally stored tokens.
Then remove the executable's version directory, symlink and PATH entry. This does not
remove configuration or the stored client secret. Only if you explicitly want to erase
those too, remove the [documented configuration directory](configuration.md#local-paths).
Logout is local token deletion, not revocation of Visma server-side consent.

## What the release verifies

Each native binary runs outside the checkout with an empty PATH: help/version, human and
JSON configuration, credential storage/decryption, and authenticated GET/POST/PUT/DELETE
against an ephemeral local HTTPS server. Tests check Unicode, ordered duplicate queries,
JSON stdin, empty responses, HTTP errors, secret redaction, 429 details, invalid input,
non-JSON responses and logout. TLS verification stays enabled using a temporary test CA;
no real Dinero credentials, live accounting writes or installed developer Python are used.
The build host requires OpenSSL to generate the one-day test certificate; it is not a
runtime dependency of the distributed binary. CI uses Ubuntu/Git Bash OpenSSL.

This verifies packaging and protocol behavior on all four runners. A real Visma consent
flow still depends on your registered application and is not claimed to be exercised by
these offline release tests.
