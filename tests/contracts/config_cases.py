"""Isolated local configuration scenarios for the production command registry."""

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from pytest import MonkeyPatch

from devtools.contracts import Case, Contract
from dinero_cli import config, storage
from dinero_cli.config import Settings


def error(message, code=2):
    return {"error": True, "status": None, "message": message, "details": {}}


@contextmanager
def fresh():
    with TemporaryDirectory() as folder, MonkeyPatch.context() as patch:
        path = Path(folder)
        patch.setenv("DINERO_CONFIG_DIR", str(path / "state"))
        patch.chdir(path)
        yield


@contextmanager
def configured():
    with fresh():
        config.save_setting("organization", "123")
        yield


@contextmanager
def invalid():
    with fresh():
        storage.atomic_write(
            config.config_directory() / "config.json", b'{"client_secret":"contract-client-secret"}'
        )
        yield


@contextmanager
def failed_read():
    with fresh(), MonkeyPatch.context() as patch:

        def fail(*args):
            raise OSError("contract-access-token")

        patch.setattr(config, "read_private", fail)
        yield


@contextmanager
def failed_write():
    with fresh(), MonkeyPatch.context() as patch:

        def fail(*args):
            raise OSError("contract-access-token")

        patch.setattr(config, "atomic_write", fail)
        yield


@contextmanager
def secret_input():
    with fresh():
        config.save_setting("credential-backend", "file")
        path = Path("secret-input.txt")
        path.write_text("contract-client-secret\n")
        path.chmod(0o600)
        yield


@contextmanager
def secret_write_failure():
    from dinero_cli import secrets

    with secret_input(), MonkeyPatch.context() as patch:

        def fail(*args):
            raise OSError("contract-client-secret")

        patch.setattr(secrets, "atomic_write", fail)
        yield


EXCLUDED = {
    "authentication": "Local public config/storage does not perform OAuth or require a token.",
    "api": "These local commands never issue an API request.",
}
INVALID = "Invalid configuration. Use config --help for supported settings."
IO = "Unable to read or write local state or output."
PARSER = "Invalid arguments. Use --help for command syntax."

CONTRACTS = {
    ("config",): Contract(
        kind="group", options=frozenset(), reason="Local configuration namespace."
    ),
    ("config", "list"): Contract(
        kind="data",
        options=frozenset({"--json"}),
        reason="Resolved public configuration data.",
        excluded_failures=EXCLUDED,
        cases=(
            Case(
                (), expected=Settings().model_dump(), human=("organization", "Not set"), setup=fresh
            ),
            Case(
                (),
                expected=Settings(organization="123").model_dump(),
                human=("organization", "123"),
                setup=configured,
            ),
            Case(
                (),
                expected=error(INVALID),
                human=(INVALID,),
                exit_code=2,
                failure="validation",
                setup=invalid,
            ),
            Case(
                (),
                expected=error(IO),
                human=(IO,),
                exit_code=5,
                failure="transport",
                setup=failed_read,
            ),
        ),
    ),
    ("config", "get"): Contract(
        kind="data",
        options=frozenset({"--json"}),
        reason="One resolved public configuration value.",
        excluded_failures=EXCLUDED,
        cases=(
            Case(
                ("organization",),
                expected={"organization": "123"},
                human=("organization", "123"),
                setup=configured,
            ),
            Case(
                ("organization",), expected={"organization": None}, human=("Not set",), setup=fresh
            ),
            Case(
                (),
                expected=error(PARSER),
                human=(PARSER,),
                exit_code=2,
                failure="validation",
                setup=fresh,
            ),
            Case(
                ("organization",),
                expected=error(IO),
                human=(IO,),
                exit_code=5,
                failure="transport",
                setup=failed_read,
            ),
        ),
    ),
    ("config", "set"): Contract(
        kind="data",
        options=frozenset({"--json"}),
        reason="Explicit local setting mutation returns the saved public value.",
        excluded_failures=EXCLUDED,
        cases=(
            Case(
                ("organization", "123"),
                expected={"organization": "123"},
                human=("organization", "123"),
                setup=fresh,
            ),
            Case(
                ("organization", "invalid"),
                expected=error(INVALID),
                human=(INVALID,),
                exit_code=2,
                failure="validation",
                setup=fresh,
            ),
            Case(
                ("organization", "123"),
                expected=error(IO),
                human=(IO,),
                exit_code=5,
                failure="transport",
                setup=failed_write,
            ),
        ),
    ),
    ("config", "set-client-secret"): Contract(
        kind="data",
        options=frozenset({"--json", "--input"}),
        reason="Explicit credential mutation reports storage status, never the secret.",
        excluded_failures=EXCLUDED,
        cases=(
            Case(
                ("--input", "secret-input.txt"),
                expected={"client_secret_stored": True},
                human=("client_secret_stored", "Yes"),
                setup=secret_input,
            ),
            Case(
                (),
                expected=error(PARSER),
                human=(PARSER,),
                exit_code=2,
                failure="validation",
                setup=fresh,
            ),
            Case(
                ("--input", "secret-input.txt"),
                expected=error(IO),
                human=(IO,),
                exit_code=5,
                failure="transport",
                setup=secret_write_failure,
            ),
        ),
    ),
}
