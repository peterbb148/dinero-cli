# Release legal inventory

Project license: Apache-2.0 subject to Commons Clause 1.0. Its SPDX-compatible custom
identifier is `LicenseRef-Apache-2.0-with-Commons-Clause-1.0`; the full definition is
in the root LICENSE. Never label the combined terms as plain Apache-2.0.

The native build reads PyInstaller's Analysis TOC and maps included files back to
installed distribution RECORDs. Unused development dependencies are not reported as
bundled. Full distribution legal directories and vendored notices are copied without
changing their terms. PyInstaller's bootloader is explicitly included in the inventory.
The reader rejects unknown native inputs, missing legal files and unreviewed Python builds.

## Runtime review

`python-licenses/runtimes.json` records all four upstream Python 3.13.11 / 20251217
full-archive URLs and SHA-256 hashes, checked against GitHub release asset digests.
License filenames are prefixed with their content hashes. The files were extracted
unchanged from `python/licenses/` in those archives. Upstream links and extension
license metadata are retained for review; they are not a claim that all extensions
are bundled. UV's install-only runtime omits these notice files, so they live here.

Sources:

- https://github.com/astral-sh/python-build-standalone/releases/tag/20251217
- https://gregoryszorc.com/docs/python-build-standalone/main/distributions.html
- CPython-third-party.rst: https://github.com/python/cpython/blob/v3.13.11/Doc/license.rst
- Microsoft-CRT.txt: https://github.com/python/cpython/blob/v3.13.11/PC/crtlicense.txt
- https://pyinstaller.org/en/stable/license.html

The CPython notice document includes embedded-code notices (including mimalloc); the upstream runtime license set additionally covers linked extension libraries.
Windows archives include CPython's Microsoft CRT redistribution terms. HACL.txt preserves the MIT header from CPython v3.13.11
Modules/_hacl/Hacl_Hash_MD5.c. The distributed
runtime stays unmodified. PyInstaller's exception permits application distribution
under its own license; the upstream COPYING.txt is nevertheless included for clarity.
Typer's vendored Click BSD notice is copied with Typer's license files.

CPython is an aggregate SBOM component with the exact Python and standalone build
versions. Statically linked sublibraries are not falsely given guessed independent
versions. The manifest identifies actual module-source and native input hashes and
binds them to the executable hash. OS-supplied libraries that are not in the archive
are external runtime requirements, not redistributed components.

Before upgrading Python: download the corresponding full archive for each target,
verify its published SHA-256, refresh the complete license sets, target/version/build
records and CPython notices, and inspect changed library/CRT terms. Before upgrading
PyInstaller: verify its Analysis TOC schema and bootloader inventory. Native CI must
produce and validate all four archives. Changes here, LICENSE, NOTICE or the notice
collector are build inputs and therefore trigger a new minor release after merge.
