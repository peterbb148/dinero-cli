"""Keep contract runs offline and away from a developer's configuration."""

import socket
import subprocess

import pytest


@pytest.fixture(autouse=True)
def isolated_cli(tmp_path, monkeypatch):
    for name in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(tmp_path))
    monkeypatch.chdir(tmp_path)
    for name in ("FORCE_COLOR", "CLICOLOR_FORCE", "NO_COLOR", "PYTHONOPTIMIZE"):
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("SAFE-001: external I/O is forbidden in contract tests")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket.socket, "sendto", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
