"""Verify legal inventory against build inputs rather than the entire environment."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import notices


def test_analysis_format_and_input_paths(tmp_path):
    toc = tmp_path / "Analysis.toc"
    toc.write_text("[]")
    with pytest.raises(ValueError, match="analysis format"):
        notices.analysis_files(toc)
    values = [[] for _ in range(20)]
    values[14] = [("module", str(tmp_path / "module.py"), "PYMODULE")]
    values[14].append(("namespace", "-", "PYMODULE"))
    toc.write_text(repr(values))
    assert notices.analysis_files(toc) == [("module", tmp_path / "module.py", "PYMODULE")]
    toc.write_text("__import__('os').system('never')")
    with pytest.raises(ValueError):
        notices.analysis_files(toc)


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "BUILD").write_text("20251217")
    monkeypatch.setattr(notices.sys, "base_prefix", str(runtime))
    monkeypatch.setattr(notices.sys, "version", "3.13.11 fixture")
    files = {}

    def write(name, content="fixture"):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    write("LICENSE", "combined license")
    write("NOTICE", "notice")
    record = {"version": "3.13.11", "build": "20251217", "licenses": ["LICENSE.txt"]}
    write(
        "packaging/python-licenses/runtimes.json",
        json.dumps(
            {
                "linux-x86_64": record,
                "windows-arm64": record,
            }
        ),
    )
    for name in ("LICENSE.txt", "CPython-third-party.rst", "Microsoft-CRT.txt", "HACL.txt"):
        write("packaging/python-licenses/" + name)
    for name in (
        "src/dinero_cli/cli.py",
        "assets/icon.png",
        "scripts/entrypoint.py",
        "runtime/python.dll",
        "build/pyinstaller/dinero/base_library.zip",
    ):
        files[name] = write(name)

    def distribution(name, paths):
        for path in paths:
            write("packages/" + path)
        return SimpleNamespace(
            name=name,
            version="1.2.3",
            files=paths,
            metadata={},
            locate_file=lambda p: tmp_path / "packages" / p,
        )

    deps = [
        distribution("pyinstaller", ["PyInstaller/bootloader/native/run", "COPYING.txt"]),
        distribution("typer", ["typer/core.py", "typer/_click/LICENSE.txt", "licenses/AUTHORS"]),
        distribution("unused", ["unused.py", "LICENSE"]),
        distribution("dinero-cli", ["dinero_cli/_version.py"]),
    ]
    deps[1].metadata["License-Expression"] = "MIT"
    write("packages/PyInstaller/bootloader/native/run.exe")
    deps[0].files.append("PyInstaller/bootloader/native/run.exe")
    toc = [[] for _ in range(21)]
    toc[20] = [("run", str(tmp_path / "packages/PyInstaller/bootloader/native/run"), "EXECUTABLE")]
    write("build/pyinstaller/dinero/EXE-00.toc", repr(toc))
    for file in ("typer/core.py", "dinero_cli/_version.py"):
        files[file] = tmp_path / "packages" / file
    monkeypatch.setattr(notices.metadata, "distributions", lambda: deps)
    monkeypatch.setattr(
        notices,
        "analysis_files",
        lambda p: [(name, source, "DATA") for name, source in files.items()],
    )
    return SimpleNamespace(executable=write("dinero"), write=write, files=files, deps=deps)


@pytest.mark.parametrize("target", ["linux-x86_64", "windows-arm64"])
def test_manifest_licenses_and_sbom_match_actual_inputs(inventory, target):
    members = notices.collect("0.2.0", target, inventory.executable)
    bom = json.loads(members["SBOM.cdx.json"])
    assert bom["bomFormat"] == "CycloneDX"
    assert {c["name"] for c in bom["components"]} == {"CPython", "pyinstaller", "typer"}
    assert bom["metadata"]["component"]["version"] == "0.2.0"
    assert bom["metadata"]["component"]["licenses"] == [{"expression": notices.LICENSE_ID}]
    manifest = json.loads(members["BUNDLE-MANIFEST.json"])
    assert manifest["executable_sha256"] == notices.sha256(inventory.executable)
    assert {
        "name": "assets/icon.png",
        "sha256": notices.sha256(inventory.files["assets/icon.png"]),
    } in manifest["inputs"]["application"]
    assert str(Path.cwd()).encode() not in members["BUNDLE-MANIFEST.json"]
    assert "licenses/typer/typer/_click/LICENSE.txt" in members
    assert "licenses/typer/licenses/AUTHORS" in members
    assert "licenses/pyinstaller/COPYING.txt" in members
    assert ("licenses/CPython/Microsoft-CRT.txt" in members) == target.startswith("windows")
    assert members["LICENSE"] == b"combined license"
    assert members["NOTICE"] == b"notice"


def test_unreviewed_runtime_is_rejected(inventory):
    inventory.write("runtime/BUILD", "different")
    with pytest.raises(ValueError, match="runtime changed"):
        notices.collect("0.2.0", "linux-x86_64", inventory.executable)


def test_unknown_native_library_is_rejected(inventory):
    inventory.files["unknown.dll"] = inventory.write("system/unknown.dll")
    with pytest.raises(ValueError, match="Unidentified bundled input"):
        notices.collect("0.2.0", "linux-x86_64", inventory.executable)


def test_missing_or_ambiguous_bootloader_is_rejected(inventory):
    inventory.write("build/pyinstaller/dinero/EXE-00.toc", repr([[] for _ in range(21)]))
    with pytest.raises(ValueError, match="bootloader"):
        notices.collect("0.2.0", "linux-x86_64", inventory.executable)


def test_distribution_without_legal_files_is_rejected(inventory):
    inventory.deps[1].files = ["typer/core.py"]
    with pytest.raises(ValueError, match="No license files"):
        notices.collect("0.2.0", "linux-x86_64", inventory.executable)


def test_vendored_runtime_notices_match_upstream_content_hashes():
    root = Path(__file__).resolve().parents[1] / "packaging/python-licenses"
    records = json.loads((root / "runtimes.json").read_text())
    assert set(records) == {"linux-x86_64", "linux-arm64", "windows-x86_64", "windows-arm64"}
    for record in records.values():
        for filename in record["licenses"]:
            assert notices.sha256(root / filename) == filename.split("-", 1)[0]


@pytest.mark.parametrize("directory", ["src", "assets"])
@pytest.mark.parametrize("kind", ["BINARY", "EXTENSION"])
def test_unknown_native_inputs_in_application_trees_are_rejected(
    inventory, monkeypatch, directory, kind
):
    native = inventory.write(f"{directory}/third-party.dll")
    monkeypatch.setattr(notices, "analysis_files", lambda p: [("third-party.dll", native, kind)])
    with pytest.raises(ValueError, match="Unidentified bundled input"):
        notices.collect("0.2.0", "linux-x86_64", inventory.executable)


def test_bundled_gcc_runtime_is_inventoried_with_its_exception(inventory, monkeypatch):
    native = inventory.write("system/libgcc_s.so.1")
    original = notices.analysis_files
    monkeypatch.setattr(
        notices,
        "analysis_files",
        lambda path: [*original(path), ("libgcc_s.so.1", native, "BINARY")],
    )
    monkeypatch.setattr(
        notices,
        "gcc_runtime",
        lambda source: ("14.2.0", {"COPYRIGHT.txt": b"GPL and GCC exception"}),
    )
    members = notices.collect("0.3.0", "linux-x86_64", inventory.executable)
    component = next(
        c for c in json.loads(members["SBOM.cdx.json"])["components"] if c["name"] == "libgcc-s1"
    )
    assert component["version"] == "14.2.0"
    assert component["licenses"] == [{"expression": "GPL-3.0-or-later WITH GCC-exception-3.1"}]
    assert members["licenses/libgcc-s1/COPYRIGHT.txt"] == b"GPL and GCC exception"


def test_gcc_ownership_version_and_original_legal_files(monkeypatch):
    source = Path("/usr/lib/example/libgcc_s.so.1")
    replies = iter([f"libgcc-s1:arm64: {source}\n", "14.2.0"])
    calls = []

    def query(args, **kwargs):
        calls.append(args)
        return next(replies)

    monkeypatch.setattr(notices.subprocess, "check_output", query)
    monkeypatch.setattr(Path, "read_bytes", lambda path: str(path).encode())
    version, texts = notices.gcc_runtime(source)
    assert version == "14.2.0" and len(texts) == 2
    assert b"/usr/share/doc/libgcc-s1/copyright" == texts["COPYRIGHT.txt"]
    assert calls[1][-1] == "libgcc-s1:arm64"
    for bad in ("other-package: /wrong", f"other-package: {source}"):
        monkeypatch.setattr(notices.subprocess, "check_output", lambda *a, **kw: bad)
        with pytest.raises(ValueError, match="not owned"):
            notices.gcc_runtime(source)
    replies = iter([f"libgcc-s1:arm64: {source}\n", ""])
    monkeypatch.setattr(notices.subprocess, "check_output", query)
    with pytest.raises(ValueError, match="version is missing"):
        notices.gcc_runtime(source)
