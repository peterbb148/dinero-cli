import json
import struct
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from dinero_cli import cli
from scripts import build


def elf(machine=62):
    data = bytearray(64)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", data, 18, machine)
    return bytes(data)


def pe(machine=0xAA64):
    data = bytearray(128)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<H", data, 68, machine)
    return bytes(data)


@pytest.mark.parametrize(
    "target,contents",
    [
        ("linux-x86_64", elf()),
        ("linux-arm64", elf(183)),
        ("windows-arm64", pe()),
        ("windows-x86_64", pe(0x8664)),
    ],
)
def test_binary_architecture(tmp_path, target, contents):
    exe = tmp_path / "dinero"
    exe.write_bytes(contents)
    build.verify_machine(exe, target)
    other = (
        target.replace("arm64", "x86_64")
        if "arm64" in target
        else target.replace("x86_64", "arm64")
    )
    with pytest.raises(ValueError, match="architecture"):
        build.verify_machine(exe, other)


@pytest.mark.parametrize("target", ["linux-x86_64", "windows-arm64"])
def test_invalid_binary_header(tmp_path, target):
    exe = tmp_path / "bad"
    exe.write_bytes(b"not a binary")
    with pytest.raises(ValueError, match="Expected"):
        build.verify_machine(exe, target)
    exe.write_bytes(pe().replace(b"PE\0\0", b"FAIL"))
    with pytest.raises(ValueError, match="signature"):
        build.verify_machine(exe, "windows-arm64")


@pytest.mark.parametrize(
    "system,machine,target",
    [
        ("linux", "aarch64", "linux-arm64"),
        ("win32", "ARM64", "windows-arm64"),
        ("win32", "AMD64", "windows-x86_64"),
    ],
)
def test_native_interpreter_selection(monkeypatch, system, machine, target):
    monkeypatch.setattr(sys, "platform", system)
    monkeypatch.setattr(build.sysconfig, "get_platform", lambda: "win-" + machine.lower())
    monkeypatch.setattr(build.platform, "machine", lambda: machine)
    assert build.native_target() == target


def test_unsupported_native_target(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(ValueError):
        build.native_target()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(build.platform, "machine", lambda: "riscv")
    with pytest.raises(ValueError):
        build.native_target()


def test_smoke_has_no_python_path_or_checkout_dependency(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("PYTHONPATH", "something")
    monkeypatch.setenv("FORCE_COLOR", "1")

    def execute(args, **kwargs):
        calls.append((args, kwargs))
        assert kwargs["encoding"] == "utf-8"
        if args[1] in {"config", "auth"}:
            from typer.testing import CliRunner

            from dinero_cli.cli import app

            result = CliRunner().invoke(app, args[1:], env=kwargs["env"], input=kwargs.get("input"))
            assert result.exit_code == 0, result.stderr
            return subprocess.CompletedProcess(args, 0, stdout=result.stdout, stderr=result.stderr)
        return subprocess.CompletedProcess(
            args, 0, stdout="0.1.0" if args[-1] == "--version" else "--version", stderr=""
        )

    monkeypatch.setattr(build.subprocess, "run", execute)
    build.smoke(tmp_path / "dinero", "0.1.0")
    assert len(calls) == 10
    for _, settings in calls:
        assert settings["env"]["PATH"] == ""
        assert "PYTHONPATH" not in settings["env"]
        assert "FORCE_COLOR" not in settings["env"]
        assert settings["env"]["NO_COLOR"] == "1"
        assert Path(settings["cwd"]) != Path.cwd()
    monkeypatch.setattr(
        build.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout="wrong", stderr=""),
    )
    with pytest.raises(ValueError, match="smoke"):
        build.smoke(tmp_path / "dinero", "0.1.0")


def test_packaging_restores_source_and_archives_real_binary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(build, "native_target", lambda: "linux-x86_64")
    path = Path("src/dinero_cli/_version.py")
    path.parent.mkdir(parents=True)
    path.write_text("original")

    def freezer(*args, **kwargs):
        assert path.read_text() == "VERSION = '0.1.0'\n"
        output = Path("dist/bin/dinero")
        output.parent.mkdir(parents=True)
        output.write_bytes(elf())

    monkeypatch.setattr(build.subprocess, "run", freezer)
    monkeypatch.setattr(build, "smoke", lambda *args: None)
    monkeypatch.setattr("scripts.notices.collect", lambda *args: {"LICENSE": b"License"})
    archive = build.build("0.1.0", "linux-x86_64")
    assert path.read_text() == "original"
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.read("dinero") == elf()
        assert json.loads(bundle.read("BUILD.json"))["version"] == "0.1.0"
    with pytest.raises(ValueError):
        build.build("not-a-version", "linux-x86_64")
    with pytest.raises(ValueError):
        build.build("0.1.0", "windows-arm64")
    monkeypatch.setattr(
        build.subprocess, "run", Mock(side_effect=subprocess.CalledProcessError(1, []))
    )
    with pytest.raises(subprocess.CalledProcessError):
        build.build("0.1.0", "linux-x86_64")
    assert path.read_text() == "original"


def test_build_command_dispatch(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(build, "build", lambda *args: "archive.zip")
    monkeypatch.setattr(sys, "argv", ["build", "build", "--target", "linux-arm64"])
    build.main()
    assert "archive.zip" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["build", "checksums", "--directory", str(tmp_path)])
    build.main()
    assert (tmp_path / "SHA256SUMS").exists()


def test_cli_help_version_and_unknown_command():
    runner = CliRunner()
    assert runner.invoke(cli.app, ["--version"]).stdout.strip() == "0.0.0.dev0"
    assert runner.invoke(cli.app, ["--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["unknown"]).exit_code != 0


def test_windows_emulation_reports_interpreter_architecture(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(build.platform, "machine", lambda: "ARM64")
    monkeypatch.setattr(build.sysconfig, "get_platform", lambda: "win-amd64")
    assert build.native_target() == "windows-x86_64"


def test_windows_freezer_cannot_collect_dlls_from_other_runner_software(monkeypatch):
    monkeypatch.setenv("SystemRoot", "C:/Windows")
    monkeypatch.setenv("PATH", "unrelated-java-runtime")
    environment = build.freezer_environment("windows-x86_64")
    assert "unrelated-java-runtime" not in environment["PATH"]
    assert "System32" in environment["PATH"]
    assert sys.base_prefix in environment["PATH"]
    assert build.freezer_environment("linux-x86_64")["PATH"] == "unrelated-java-runtime"
