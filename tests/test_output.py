"""Actual parser/output behavior, including secret input and safe failures."""

import json

import pytest
from typer.core import Abort
from typer.testing import CliRunner

from dinero_cli import config, output, secrets
from dinero_cli.cli import app
from dinero_cli.config import Settings


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("DINERO_CONFIG_DIR", str(tmp_path / "state"))
    for name in Settings.model_fields:
        monkeypatch.delenv("DINERO_" + name.upper(), raising=False)
    return CliRunner()


@pytest.mark.parametrize("value", [None, [], {}, [1, {"Name": "Åse"}], {"lines": [1, 2]}, "scalar"])
def test_human_and_json_shapes(value, capsys):
    output.emit(value, json_mode=True)
    captured = capsys.readouterr()
    assert json.loads(captured.out) == value and not captured.err
    output.emit(value)
    captured = capsys.readouterr()
    assert captured.out.strip() and not captured.err
    if isinstance(value, (dict, list)):
        with pytest.raises(ValueError):
            json.loads(captured.out)


def test_escape_characters_do_not_execute_terminal_markup(capsys):
    output.emit({"value": "\x1b[31m[red]sentinel[/red]"})
    actual = capsys.readouterr().out
    assert "\x1b" not in actual and "[red]sentinel[/red]" in actual


def test_secret_stdin_and_saved_json_preference(cli):
    assert cli.invoke(app, ["config", "set", "credential-backend", "file"]).exit_code == 0
    result = cli.invoke(
        app, ["config", "set-client-secret", "--input", "-", "--json"], input="sentinel-secret\n"
    )
    assert result.exit_code == 0 and json.loads(result.stdout) == {"client_secret_stored": True}
    assert "sentinel" not in result.stdout + result.stderr
    result = cli.invoke(app, ["config", "set", "output", "json"])
    assert result.exit_code == 0 and json.loads(result.stdout) == {"output": "json"}
    result = cli.invoke(app, ["config", "list"])
    assert result.exit_code == 0 and "sentinel" not in result.stdout
    assert json.loads(result.stdout)["output"] == "json"
    with secrets.SecretStore(config.load_settings()).transaction() as txn:
        assert txn.state.client_secret.get_secret_value() == "sentinel-secret"


@pytest.mark.parametrize("value", ["", "   ", "line\nsecret", "nul\x00secret"])
def test_bad_secret_input_is_redacted(cli, value):
    config.save_setting("credential-backend", "file")
    result = cli.invoke(app, ["config", "set-client-secret", "--input", "-", "--json"], input=value)
    assert result.exit_code == 2 and not result.stdout
    assert json.loads(result.stderr)["status"] is None
    assert "line" not in result.stderr.replace("nonempty line", "")
    assert not (config.config_directory() / "credentials.bin").exists()


def test_non_utf8_secret_file_is_rejected(cli, tmp_path):
    config.save_setting("credential-backend", "file")
    file = tmp_path / "secret.txt"
    file.write_bytes(b"\xff")
    file.chmod(0o600)
    result = cli.invoke(app, ["config", "set-client-secret", "--input", str(file), "--json"])
    assert result.exit_code == 2 and not result.stdout
    assert json.loads(result.stderr)["message"] == "Client secret input must be UTF-8."


def test_missing_files_and_unknown_parser_values_are_not_echoed(cli):
    config.save_setting("credential-backend", "file")
    for args, code in [
        (["config", "get", "--sentinel-secret"], 2),
        (["config", "set-client-secret", "--input", "sentinel-secret-missing-file"], 5),
    ]:
        result = cli.invoke(app, [*args, "--json"])
        assert result.exit_code == code and not result.stdout
        assert "sentinel-secret" not in result.stderr
        assert json.loads(result.stderr)["error"] is True


def test_abort_and_keyboard_interrupt_have_nonzero_status(cli, monkeypatch):
    from dinero_cli.commands import config as commands

    def abort():
        raise Abort()

    monkeypatch.setattr(commands, "load_settings", abort)
    result = cli.invoke(app, ["config", "list", "--json"])
    assert result.exit_code == 130 and json.loads(result.stderr)["error"] is True

    def interrupt():
        raise KeyboardInterrupt()

    monkeypatch.setattr(commands, "load_settings", interrupt)
    assert cli.invoke(app, ["config", "list"]).exit_code == 130


def test_empty_token_only_state_roundtrip(cli):
    config.save_setting("credential-backend", "file")
    with secrets.SecretStore(config.load_settings()).transaction() as txn:
        txn.state.tokens = {"access_token": "sentinel"}
        txn.save()
    with secrets.SecretStore(config.load_settings()).transaction() as txn:
        assert txn.state.client_secret is None and txn.state.tokens["access_token"] == "sentinel"
