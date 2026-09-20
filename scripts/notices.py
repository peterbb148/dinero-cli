"""Generate offline notices and a CycloneDX inventory from PyInstaller build inputs."""

import ast
import hashlib
import importlib.metadata as metadata
import json
import re
import sys
from pathlib import Path

LICENSE_ID = "LicenseRef-Apache-2.0-with-Commons-Clause-1.0"
LEGAL = re.compile(r"license|licence|copying|copyright|notice|authors", re.I)


def sha256(path: Path) -> str:
    """Hash an actual build input or executable."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analysis_files(path: Path) -> list[tuple[str, Path, str]]:
    """Read the pinned PyInstaller Analysis TOC, never evaluate Python code."""
    data = ast.literal_eval(path.read_text(encoding="utf-8"))
    if len(data) != 20:
        raise ValueError("Unsupported PyInstaller analysis format; review the inventory reader")
    return sorted(
        {
            (name, Path(source).resolve(), kind)
            for index in (13, 14, 15, 18, 19)
            for name, source, kind in data[index]
            if source
        }
    )


def package_licenses(dist: metadata.Distribution) -> dict[str, bytes]:
    """Include complete legal directories, including nested vendored licenses."""
    result = {}
    for file in dist.files or ():
        if LEGAL.search(str(file)):
            result[str(file)] = Path(str(dist.locate_file(file))).read_bytes()
    if not result:
        raise ValueError(f"No license files found for bundled distribution {dist.name}")
    return result


def collect(version: str, target: str, executable: Path) -> dict[str, bytes]:
    """Return archive members; fail on unidentified inputs or unreviewed Python builds.

    CPython is an aggregate component, including its statically linked libraries.
    All upstream runtime notices are retained conservatively, even for unused extensions.
    Source hashes identify frozen-module inputs; the executable hash binds the final output.
    """
    root = Path.cwd().resolve()
    runtime = Path(sys.base_prefix).resolve()
    legal_root = root / "packaging/python-licenses"
    record = json.loads((legal_root / "runtimes.json").read_text())[target]
    if (
        record["version"] != sys.version.split()[0]
        or (runtime / "BUILD").read_text().strip() != record["build"]
    ):
        raise ValueError("Python runtime changed; refresh the reviewed runtime notices")
    members = {name: (root / name).read_bytes() for name in ("LICENSE", "NOTICE")}
    component_files: dict[str, list[dict[str, str]]] = {}
    distributions = {dist.name: dist for dist in metadata.distributions()}
    owners = {
        Path(str(dist.locate_file(file))).resolve(): name
        for name, dist in distributions.items()
        for file in dist.files or ()
    }
    files = analysis_files(root / "build/pyinstaller/dinero/Analysis-00.toc")
    # The bootloader is linked into the final executable, but is not an Analysis entry.
    installer = distributions["pyinstaller"]
    boot = Path(str(installer.locate_file("PyInstaller/bootloader")))
    executable_toc = ast.literal_eval(
        (root / "build/pyinstaller/dinero/EXE-00.toc").read_text(encoding="utf-8")
    )
    bootloaders = [
        Path(source).resolve() for name, source, kind in executable_toc[20] if kind == "EXECUTABLE"
    ]
    if len(bootloaders) != 1 or not bootloaders[0].is_relative_to(boot.resolve()):
        raise ValueError("Expected one native PyInstaller bootloader")
    files.append(("PyInstaller/bootloader", bootloaders[0], "EXECUTABLE"))
    for name, source, kind in files:
        if source in owners:
            owner = owners[source]
            if owner == "dinero-cli":
                owner = "application"
        elif source.is_relative_to(runtime) and "site-packages" not in source.parts:
            owner = "CPython"
        elif kind not in {"BINARY", "EXTENSION", "EXECUTABLE"} and (
            source.is_relative_to(root / "src")
            or source.is_relative_to(root / "assets")
            or source == root / "scripts/entrypoint.py"
        ):
            owner = "application"
        elif source == root / "build/pyinstaller/dinero/base_library.zip":
            owner = "CPython"
        else:
            raise ValueError(f"Unidentified bundled input: {name} ({source})")
        component_files.setdefault(owner, []).append({"name": name, "sha256": sha256(source)})
    components = []
    for name, inventory in sorted(component_files.items()):
        if name == "application":
            continue
        if name == "CPython":
            component_version = record["version"] + "+" + record["build"]
            license_name = "CPython and bundled-library terms; see licenses/CPython"
            texts = {file: (legal_root / file).read_bytes() for file in record["licenses"]}
            texts["CPython-third-party.rst"] = (legal_root / "CPython-third-party.rst").read_bytes()
            texts["HACL.txt"] = (legal_root / "HACL.txt").read_bytes()
            if target.startswith("windows"):
                texts["Microsoft-CRT.txt"] = (legal_root / "Microsoft-CRT.txt").read_bytes()
        else:
            dist = distributions[name]
            component_version = dist.version
            license_name = f"See licenses/{name}"
            texts = package_licenses(dist)
        for filename, content in texts.items():
            members[f"licenses/{name}/{filename}"] = content
        components.append(
            {
                "type": "library",
                "bom-ref": name,
                "name": name,
                "version": component_version,
                "licenses": (
                    [{"expression": distributions[name].metadata["License-Expression"]}]
                    if name != "CPython" and distributions[name].metadata.get("License-Expression")
                    else [{"license": {"name": license_name}}]
                ),
            }
        )
    app = {
        "type": "application",
        "bom-ref": "application",
        "name": "dinero-cli",
        "version": version,
        "licenses": [{"expression": LICENSE_ID}],
        "hashes": [{"alg": "SHA-256", "content": sha256(executable)}],
        "properties": [{"name": "dinero:target", "value": target}],
    }
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {"component": app},
        "components": components,
        "dependencies": [{"ref": "application", "dependsOn": [c["bom-ref"] for c in components]}],
    }
    members["SBOM.cdx.json"] = (json.dumps(bom, indent=2, sort_keys=True) + "\n").encode()
    manifest = {
        "runtime": record,
        "inputs": component_files,
        "executable_sha256": sha256(executable),
    }
    members["BUNDLE-MANIFEST.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode()
    names = "\n".join(f"- {c['name']} {c['version']}" for c in components)
    members["THIRD-PARTY-NOTICES.md"] = (
        "# Bundled components\n\n" + names + "\n\n"
        "Full original licenses and notices are in licenses/. Typer includes vendored Click; "
        "its BSD license is retained there. PyInstaller's bootloader/runtime hooks retain "
        "the upstream GPL exception and Apache terms in COPYING.txt.\n\n"
        "CPython is inventoried as a runtime aggregate, including statically linked libraries. "
        "Its complete upstream notice set is included; presence of a notice does not claim "
        "every optional extension is shipped. BUNDLE-MANIFEST.json records the actual frozen "
        "module source and native-library input hashes, plus runtime archive provenance. "
        "The SBOM is bound to the final executable hash. Host OS libraries are not distributed.\n"
    ).encode()
    return members
