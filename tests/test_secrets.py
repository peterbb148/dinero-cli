"""Real process contention, safe persistence and the Win32 DPAPI boundary."""

import ctypes
import subprocess
import sys
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from dinero_cli import secrets, storage, windows
from dinero_cli.config import Settings
from dinero_cli.errors import CLIError


def test_storage_requires_explicit_backend(tmp_path):
    with pytest.raises(CLIError, match="Select protected storage"):
        secrets.SecretStore(Settings(), tmp_path)


def test_complete_secret_record_roundtrip_and_no_repr_disclosure(tmp_path):
    store = secrets.SecretStore(Settings(credential_backend="file"), tmp_path / "private")
    with store.transaction() as transaction:
        assert transaction.state.client_secret is None
        transaction.state.client_secret = SecretStr("sentinel-client-secret")
        transaction.state.tokens = {"access_token": "long-token-" * 1000}
        assert "sentinel" not in repr(transaction)
        assert "long-token" not in repr(transaction.state)
        transaction.save()
    with store.transaction() as transaction:
        assert transaction.state.client_secret.get_secret_value() == "sentinel-client-secret"
        assert transaction.state.tokens == {"access_token": "long-token-" * 1000}


def test_store_uses_config_directory_and_reports_invalid_record(tmp_path, monkeypatch):
    monkeypatch.setenv("DINERO_CONFIG_DIR", str(tmp_path / "state"))
    store = secrets.SecretStore(Settings(credential_backend="file"))
    storage.atomic_write(store.directory / "credentials.bin", b'{"unexpected":"sentinel"}')
    with pytest.raises(CLIError) as failure:
        with store.transaction():
            pytest.fail("Invalid credentials must not be accepted")
    assert "sentinel" not in failure.value.message


def test_windows_protection_no_plaintext_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "WINDOWS", True)
    calls = []

    def crypto(value, *, decrypt=False):
        calls.append(decrypt)
        return value[::-1]

    monkeypatch.setattr(secrets, "protect", crypto)
    store = secrets.SecretStore(Settings(credential_backend="file"), tmp_path / "state")
    with store.transaction() as transaction:
        transaction.state.client_secret = SecretStr("sentinel")
        transaction.save()
    raw = (store.directory / "credentials.bin").read_bytes()
    assert raw.startswith(secrets.WINDOWS_HEADER) and b"sentinel" not in raw
    with store.transaction() as transaction:
        assert transaction.state.client_secret.get_secret_value() == "sentinel"
    assert calls == [False, True]
    storage.atomic_write(store.directory / "credentials.bin", b"unprotected")
    with pytest.raises(CLIError, match="not Windows-protected"):
        with store.transaction():
            pytest.fail("No plaintext fallback")


def test_process_lock_timeout_is_explicit(tmp_path):
    directory = tmp_path / "state"
    with storage.locked(directory):
        with pytest.raises(CLIError, match="busy"):
            with storage.locked(directory, timeout=0):
                pytest.fail("Independent lock must not be reentrant")


def test_concurrent_processes_do_not_lose_credential_updates(tmp_path):
    directory = tmp_path / "state"
    code = """
import sys,time
from pathlib import Path
from dinero_cli.config import Settings
from dinero_cli.secrets import SecretStore
with SecretStore(Settings(credential_backend="file"), Path(sys.argv[1])).transaction() as txn:
    count = (txn.state.tokens or {}).get("counter", 0)
    time.sleep(0.04)
    txn.state.tokens = {"counter": count + 1}
    txn.save()
"""
    processes = [subprocess.Popen([sys.executable, "-c", code, str(directory)]) for _ in range(4)]
    assert [p.wait(timeout=20) for p in processes] == [0] * 4
    with secrets.SecretStore(Settings(credential_backend="file"), directory).transaction() as txn:
        assert txn.state.tokens == {"counter": 4}


@pytest.mark.parametrize("decrypt", [False, True])
@pytest.mark.parametrize("success", [False, True])
def test_dpapi_abi_flags_and_buffer_release(monkeypatch, decrypt, success):
    allocation = ctypes.create_string_buffer(b"protected-result")
    calls = []

    class Operation:
        def __call__(self, source, description, entropy, reserved, prompt, flags, target):
            blob = ctypes.cast(source, ctypes.POINTER(windows.Blob)).contents
            assert ctypes.string_at(blob.data, blob.size) == b"input-secret"
            assert (description, entropy, reserved, prompt, flags) == (None, None, None, None, 1)
            result = ctypes.cast(target, ctypes.POINTER(windows.Blob)).contents
            result.size = len(b"protected-result")
            result.data = ctypes.cast(allocation, ctypes.POINTER(ctypes.c_ubyte))
            calls.append("unprotect" if decrypt else "protect")
            return success

    class Free:
        def __call__(self, value):
            calls.append("free")

    operation = Operation()
    crypt = SimpleNamespace(
        **{("CryptUnprotectData" if decrypt else "CryptProtectData"): operation}
    )
    kernel = SimpleNamespace(LocalFree=Free())
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda name, **kw: crypt if name == "crypt32" else kernel, raising=False
    )
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    if success:
        assert windows.protect(b"input-secret", decrypt=decrypt) == b"protected-result"
        assert calls[-1] == "free"
    else:
        with pytest.raises(CLIError, match="protection failed") as failure:
            windows.protect(b"input-secret", decrypt=decrypt)
        assert failure.value.code == 5
        assert failure.value.details == {"winerror": 5}
        assert "free" not in calls
