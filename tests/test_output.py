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


@pytest.mark.parametrize("failure", [KeyboardInterrupt, EOFError])
def test_interruptions_have_one_json_error_and_no_noise(cli, monkeypatch, failure):
    from dinero_cli.commands import config as commands

    def interrupt():
        raise failure()

    monkeypatch.setattr(commands, "load_settings", interrupt)
    result = cli.invoke(app, ["config", "list", "--json"])
    assert result.exit_code == 130 and result.stdout == ""
    assert result.stderr.startswith('{"error": true')
    assert json.loads(result.stderr)["message"] == "Input was interrupted."


def test_parser_errors_use_saved_or_environment_json_preference(cli, monkeypatch):
    config.save_setting("output", "json")
    result = cli.invoke(app, ["config", "get"])
    assert result.exit_code == 2 and json.loads(result.stderr)["status"] is None
    monkeypatch.setenv("DINERO_OUTPUT", "human")
    result = cli.invoke(app, ["config", "get"])
    assert result.stderr.startswith("Error:")
    monkeypatch.setenv("DINERO_OUTPUT", "json")
    result = cli.invoke(app, ["config", "set", "output", "human"])
    assert json.loads(result.stdout) == {"output": "human"}


def test_json_error_selection_handles_broken_config_without_hiding_error(cli):
    from dinero_cli import storage

    storage.atomic_write(config.config_directory() / "config.json", b"not JSON")
    result = cli.invoke(app, ["config", "list"])
    assert result.exit_code == 2 and result.stderr.startswith("Error:")
    result = cli.invoke(app, ["config", "list", "--json"])
    assert result.exit_code == 2 and json.loads(result.stderr)["error"] is True
    assert cli.invoke(app, ["--help"]).exit_code == 0


def test_terminal_controls_are_safe_in_keys_nested_values_and_errors(capsys):
    from dinero_cli.errors import CLIError

    output.emit({"key\x1b": {"nested\x07": "value\r\x9b\ud800"}})
    output.emit_error(CLIError("bad\x1b\x07", details={"value": "\r\x9b"}), json_mode=False)
    capture = capsys.readouterr()
    for stream in (capture.out, capture.err):
        assert all(char not in stream for char in ("\x1b", "\x07", "\r", "\x9b", "\ud800"))
    assert "nested" in capture.out and "value" in capture.err


@pytest.mark.parametrize("value", [float("nan"), {"unsupported": {1, 2}}, "\ud800"])
def test_serialization_failure_does_not_write_partial_json(value, capsys):
    from dinero_cli.errors import CLIError

    with pytest.raises(CLIError) as failure:
        output.emit(value, json_mode=True)
    assert failure.value.code == 5 and capsys.readouterr() == ("", "")


def test_closed_stdout_is_quiet_in_actual_data_and_help_processes(tmp_path):
    import os
    import subprocess
    import sys

    for args in (["config", "list", "--json"], ["--help"]):
        process = subprocess.Popen(
            [sys.executable, "-c", "from dinero_cli.cli import main; main()", *args],
            env={**os.environ, "DINERO_CONFIG_DIR": str(tmp_path / "state")},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process.stdout.close()
        stderr = process.stderr.read()
        assert process.wait(timeout=10) == 5
        assert stderr == b""


def test_closed_stderr_is_quiet_in_actual_error_process(tmp_path):
    import os
    import subprocess
    import sys

    process = subprocess.Popen(
        [sys.executable, "-c", "from dinero_cli.cli import main; main()", "--unknown", "--json"],
        env={**os.environ, "DINERO_CONFIG_DIR": str(tmp_path / "state")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    process.stderr.close()
    assert process.stdout.read() == b""
    assert process.wait(timeout=10) == 5


def test_unexpected_failures_are_sanitized_in_actual_entrypoint(tmp_path):
    import os
    import subprocess
    import sys

    code = """
from dinero_cli.cli import main
from dinero_cli.commands import config
class Unanticipated(Exception): pass
def failure(): raise Unanticipated("sentinel-secret")
config.load_settings=failure
main()
"""
    result = subprocess.run(
        [sys.executable, "-c", code, "config", "list", "--json"],
        env={**os.environ, "DINERO_CONFIG_DIR": str(tmp_path / "state")},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1 and result.stdout == ""
    assert json.loads(result.stderr)["message"] == "Unexpected internal failure."
    assert "sentinel" not in result.stderr and "Traceback" not in result.stderr


def test_entrypoint_emits_utf8_even_with_ascii_environment(tmp_path):
    import os
    import subprocess
    import sys

    code = "from dinero_cli.cli import main; main()"
    result = subprocess.run(
        [sys.executable, "-c", code, "config", "set", "client-id", "Æble", "--json"],
        env={
            **os.environ,
            "DINERO_CONFIG_DIR": str(tmp_path / "state"),
            "PYTHONIOENCODING": "ascii",
        },
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0 and not result.stderr
    assert json.loads(result.stdout.decode("utf-8")) == {"client_id": "Æble"}


def test_safe_entrypoint_and_hook_are_measured_in_process(cli, monkeypatch):
    import io
    import sys

    from dinero_cli import cli as boundary

    class Stream(io.StringIO):
        def reconfigure(self, **kwargs):
            assert kwargs == {"encoding": "utf-8", "errors": "strict"}

    stdout, stderr = Stream(), Stream()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(sys, "argv", ["dinero", "config", "get", "organization", "--json"])
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    boundary.main()
    assert json.loads(stdout.getvalue()) == {"organization": None}
    with pytest.raises(SystemExit) as exit:
        sys.excepthook(RuntimeError, RuntimeError("sentinel"), None)
    assert exit.value.code == 1 and "sentinel" not in stderr.getvalue()


def test_output_failure_guards_with_in_memory_streams(cli, monkeypatch):
    import io

    from dinero_cli import cli as boundary
    from dinero_cli.commands import config as commands
    from dinero_cli.errors import CLIError

    def broken(*args, **kwargs):
        raise BrokenPipeError()

    monkeypatch.setattr(commands, "emit", broken)
    result = cli.invoke(app, ["config", "list", "--json"])
    assert result.exit_code == 5 and not result.stdout and not result.stderr
    monkeypatch.setattr(boundary, "emit_error", broken)
    monkeypatch.setattr(boundary.sys, "stderr", io.StringIO())
    with pytest.raises(SystemExit) as exit:
        boundary.fail(CLIError("safe"), json_mode=True)
    assert exit.value.code == 5


def test_parser_help_broken_pipe_and_explicit_interrupt_status(cli, monkeypatch):
    from typer.core import TyperGroup

    def broken(*args, **kwargs):
        raise BrokenPipeError()

    with monkeypatch.context() as patch:
        patch.setattr(TyperGroup, "make_context", broken)
        result = cli.invoke(app, ["--help"])
        assert result.exit_code == 5 and not result.stderr
    for code in (130, 7):
        with monkeypatch.context() as patch:
            patch.setattr(TyperGroup, "main", lambda *args, **kwargs: code)
            result = cli.invoke(app, ["config", "list", "--json"])
            assert result.exit_code == code
            if code == 130:
                assert json.loads(result.stderr)["error"] is True


def test_error_human_output_includes_http_status_and_safe_details(capsys):
    from dinero_cli.errors import CLIError

    output.emit_error(
        CLIError("Rejected", status=400, details={"response": {"Code": 42}}), json_mode=False
    )
    result = capsys.readouterr()
    assert not result.out and "HTTP 400" in result.err and "42" in result.err


def test_invalid_stdin_secret_is_rejected_before_storage(cli, monkeypatch):
    import io

    from dinero_cli.commands import config as commands
    from dinero_cli.errors import CLIError

    config.save_setting("credential-backend", "file")
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(b"\xff"), encoding="utf-8", errors="surrogateescape"),
    )
    with pytest.raises(CLIError, match="must be UTF-8"):
        commands.set_client_secret("-", True)
    assert not (config.config_directory() / "credentials.bin").exists()
