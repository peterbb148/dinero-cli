"""Configuration precedence and local state failure boundaries."""

import json
import os
from pathlib import Path

import pytest

from dinero_cli import config, storage
from dinero_cli.errors import CLIError


@pytest.fixture
def state(tmp_path, monkeypatch):
    directory = tmp_path / "state"
    monkeypatch.setenv("DINERO_CONFIG_DIR", str(directory))
    for key in config.Settings.model_fields:
        monkeypatch.delenv("DINERO_" + key.upper(), raising=False)
    return directory


def test_empty_config_read_does_not_create_state(state):
    assert config.load_settings().organization is None
    assert not state.exists()
    with pytest.raises(CLIError, match="Select an organization"):
        config.require_organization(config.load_settings())


def test_precedence_and_writes_do_not_persist_environment(state, monkeypatch):
    config.save_setting("organization", "123")
    monkeypatch.setenv("DINERO_ORGANIZATION", "456")
    monkeypatch.setenv("DINERO_CLIENT_ID", "environment-client")
    assert config.load_settings().organization == "456"
    assert config.require_organization(config.load_settings(organization="789")) == "789"
    config.save_setting("output", "json")
    saved = json.loads((state / "config.json").read_text())
    assert saved == {"organization": "123", "output": "json"}
    monkeypatch.setenv("DINERO_ORGANIZATION", "")
    with pytest.raises(CLIError, match="Invalid configuration"):
        config.load_settings()


def test_trust_is_saved_only_and_urls_are_normalized(state, monkeypatch):
    monkeypatch.setenv("DINERO_API_BASE_URL", "https://example.test")
    monkeypatch.setenv("DINERO_TRUSTED_API_ORIGINS", "https://example.test")
    with pytest.raises(CLIError, match="allowlist"):
        config.require_trusted_origin(config.load_settings())
    config.save_setting("trusted-api-origins", "https://EXAMPLE.test:443,https://example.test")
    settings = config.load_settings()
    assert settings.trusted_api_origins == ["https://example.test:443"]
    assert config.require_trusted_origin(settings) == "https://example.test:443"
    assert config.https_origin("https://[::1]:8443/") == "https://[::1]:8443"


@pytest.mark.parametrize(
    "value",
    [
        "http://example.test",
        "https://u:p@example.test",
        "https://example.test/path",
        "https://example.test?x=1",
        "https://example.test#x",
        "https://example.test:99999",
        "https://example.test:0",
        "https://example.test\\path",
        "https://example.test\n",
    ],
)
def test_unsafe_origin_is_rejected(state, value):
    with pytest.raises(CLIError, match="Invalid configuration"):
        config.save_setting("api-base-url", value)
    assert not (state / "config.json").exists()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("organization", "１２３"),
        ("organization", "not-an-id"),
        ("client-id", ""),
        ("client-id", "sentinel\nsecret"),
        ("scopes", ""),
        ("pkce", "invalid"),
        ("response-mode", "invalid"),
        ("output", "yaml"),
        ("credential-backend", "plaintext"),
        ("redirect-uri", "https://evil.test/callback"),
        ("redirect-uri", "http://127.0.0.1/callback"),
        ("redirect-uri", "http://user:password@127.0.0.1:123/callback"),
    ],
)
def test_invalid_settings_never_persist_or_echo_values(state, key, value):
    with pytest.raises(CLIError) as failure:
        config.save_setting(key, value)
    assert "sentinel" not in failure.value.message
    assert not (state / "config.json").exists()


def test_secret_keys_cannot_enter_public_config(state):
    with pytest.raises(CLIError, match="Unknown setting"):
        config.save_setting("client-secret", "sentinel-secret")
    storage.ensure_directory(state)
    storage.atomic_write(state / "config.json", b'{"client_secret":"sentinel-secret"}')
    with pytest.raises(CLIError) as failure:
        config.load_settings()
    assert "sentinel-secret" not in str(failure.value)


@pytest.mark.parametrize("raw", [b"not-json", b"\xff", b"[]", b"null"])
def test_invalid_saved_config_has_safe_failure(state, raw):
    storage.atomic_write(state / "config.json", raw)
    with pytest.raises(CLIError):
        config.load_settings()


def test_platform_default_directory_and_empty_override(state, monkeypatch):
    monkeypatch.delenv("DINERO_CONFIG_DIR")
    monkeypatch.setattr(config, "user_config_path", lambda *a, **kw: Path("platform-private"))
    assert config.config_directory() == Path("platform-private")
    monkeypatch.setenv("DINERO_CONFIG_DIR", "")
    with pytest.raises(CLIError, match="must not be empty"):
        config.config_directory()


def test_atomic_failure_preserves_previous_file_and_cleans_temp(state, monkeypatch):
    path = state / "config.json"
    storage.atomic_write(path, b"old")

    def fail(*args):
        raise OSError("disk failure containing sentinel-secret")

    monkeypatch.setattr(storage.os, "replace", fail)
    with pytest.raises(OSError):
        storage.atomic_write(path, b"new")
    assert path.read_bytes() == b"old"
    assert sorted(p.name for p in state.iterdir()) == ["config.json"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX file ownership and mode policy")
def test_private_modes_ownership_links_and_types(state, monkeypatch):
    path = state / "config.json"
    storage.atomic_write(path, b"{}")
    assert state.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    with pytest.raises(CLIError, match="permissions"):
        storage.read_private(path)
    path.chmod(0o600)
    with monkeypatch.context() as patch:
        patch.setattr(storage.os, "getuid", lambda: path.stat().st_uid + 1)
        with pytest.raises(CLIError, match="permissions"):
            storage.read_private(path)
    with pytest.raises(CLIError, match="file type"):
        storage.check_private(state)
    link = state / "link"
    link.symlink_to(path)
    with pytest.raises(CLIError, match="symbolic"):
        storage.read_private(link)
    with pytest.raises(CLIError, match="symbolic"):
        storage.atomic_write(link, b"replacement")
    (state / "state.lock").symlink_to(path)
    with pytest.raises(CLIError, match="symbolic"):
        with storage.locked(state):
            pytest.fail("Unsafe lock should not be acquired")
