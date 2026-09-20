"""Build and verify one native, standalone Dinero executable."""

import argparse
import hashlib
import json
import os
import platform
import re
import struct
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path

ARCHES = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}


def native_target() -> str:
    """Require a supported 64-bit native interpreter and operating system."""
    if sys.platform not in {"linux", "win32"} or sys.maxsize <= 2**32:
        raise ValueError("Build requires 64-bit Windows or Linux")
    machine = platform.machine().lower()
    if sys.platform == "win32":
        machine = sysconfig.get_platform().removeprefix("win-")
    arch = ARCHES.get(machine)
    if arch is None:
        raise ValueError("Unsupported native architecture")
    return f"{'windows' if sys.platform == 'win32' else 'linux'}-{arch}"


def verify_machine(executable: Path, target: str) -> None:
    """Validate PE/ELF machine headers; emulated x64 is not an ARM64 build."""
    data = executable.read_bytes()
    arch = target.rsplit("-", 1)[1]
    if target.startswith("linux-"):
        if len(data) < 64 or data[:6] != b"\x7fELF\x02\x01":
            raise ValueError("Expected little-endian ELF64")
        machine = struct.unpack_from("<H", data, 18)[0]
        expected = {"x86_64": 62, "arm64": 183}[arch]
    else:
        if len(data) < 64 or data[:2] != b"MZ":
            raise ValueError("Expected Windows executable")
        offset = struct.unpack_from("<I", data, 60)[0]
        if offset + 6 > len(data) or data[offset : offset + 4] != b"PE\0\0":
            raise ValueError("Invalid PE signature")
        machine = struct.unpack_from("<H", data, offset + 4)[0]
        expected = {"x86_64": 0x8664, "arm64": 0xAA64}[arch]
    if machine != expected:
        raise ValueError(f"Wrong executable architecture for {target}")


def smoke(executable: Path, version: str) -> None:
    """Run the binary outside the checkout with no Python on PATH."""
    environment = os.environ.copy()
    environment["PATH"] = ""
    environment["NO_COLOR"] = "1"
    environment["TERM"] = "dumb"
    environment.pop("FORCE_COLOR", None)
    environment.pop("CLICOLOR_FORCE", None)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    with tempfile.TemporaryDirectory() as directory:
        for option, expected in [("--version", version), ("--help", "--version")]:
            result = subprocess.run(
                [str(executable.resolve()), option],
                cwd=directory,
                env=environment,
                check=True,
                text=True,
                capture_output=True,
            )
            if expected not in result.stdout or result.stderr:
                raise ValueError(f"Standalone smoke test failed: {option}")


def freezer_environment(target: str) -> dict[str, str]:
    """Keep unrelated runner software out of Windows DLL dependency discovery."""
    environment = os.environ.copy()
    if target.startswith("windows"):
        windows = Path(os.environ["SystemRoot"])
        environment["PATH"] = os.pathsep.join(
            str(p)
            for p in (Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs", windows / "System32")
        )
    return environment


def build(version: str, target: str) -> Path:
    """Freeze, smoke-test and archive the native executable, restoring source version."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:\.dev[0-9]+)?", version):
        raise ValueError("Invalid build version")
    if target != native_target():
        raise ValueError("Requested target differs from the native build interpreter")
    version_file = Path("src/dinero_cli/_version.py")
    original = version_file.read_text()
    try:
        version_file.write_text(f"VERSION = {version!r}\n")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onefile",
                "--name",
                "dinero",
                "--paths",
                "src",
                "--distpath",
                "dist/bin",
                "--workpath",
                "build/pyinstaller",
                "--specpath",
                "build",
                "scripts/entrypoint.py",
            ],
            check=True,
            env=freezer_environment(target),
        )
        exe = Path("dist/bin") / ("dinero.exe" if target.startswith("windows") else "dinero")
        verify_machine(exe, target)
        smoke(exe, version)
        from scripts.notices import collect

        legal = collect(version, target, exe)
        directory = Path("dist/archives")
        directory.mkdir(parents=True, exist_ok=True)
        archive = directory / f"dinero-v{version}-{target}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            output.write(exe, exe.name)
            for name, content in legal.items():
                output.writestr(name, content)
            output.writestr("BUILD.json", json.dumps({"version": version, "target": target}))
        return archive
    finally:
        version_file.write_text(original)


def checksums(directory: Path) -> None:
    """Generate the checksum manifest after all native jobs have succeeded."""
    lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
        for p in sorted(directory.glob("*.zip"))
    ]
    (directory / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def main() -> None:
    """Dispatch the portable build helper."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "checksums"])
    parser.add_argument("--version", default="0.0.0.dev0")
    parser.add_argument("--target")
    parser.add_argument("--directory", type=Path, default=Path("dist/release"))
    args = parser.parse_args()
    if args.command == "build":
        print(build(args.version, args.target or native_target()))
    else:
        checksums(args.directory)


if __name__ == "__main__":
    main()
