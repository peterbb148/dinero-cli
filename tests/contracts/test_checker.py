"""Adversarial miniature CLIs prove the checker rejects contract violations."""

import json
import socket
import subprocess
from dataclasses import replace

import pytest
import typer

from devtools.contracts import Case, Contract, check, decode, discover

SECRET = "contract-access-token"
PAYLOADS = {"object": {"Name": "Acme"}, "list": [{"Name": "Acme"}], "empty": [], "null": None}
ERROR = {"error": True, "status": 400, "message": "Bad request", "details": {"field": "Name"}}
OPTIONS = frozenset({"--json", "--scenario"})


def sample(defect="", nested=False):
    app = typer.Typer(add_completion=False)

    @app.command()
    def show(
        machine: bool = typer.Option(False, "--json"),
        scenario: str = typer.Option("object", "--scenario"),
    ):
        if scenario == "error":
            error = ERROR if defect != "wrong-status" else {**ERROR, "status": 500}
            typer.echo(
                json.dumps(error) if machine else "Bad request", err=defect != "error-stdout"
            )
            raise typer.Exit(3)
        payload = PAYLOADS[scenario]
        if defect == "exit":
            raise typer.Exit(4)
        if machine:
            if defect == "noise":
                typer.echo("Fetching...")
            if defect == "ansi":
                typer.echo("\x1b[31m", nl=False, color=True)
            if defect == "secret":
                typer.echo(SECRET, err=True)
            if defect == "stderr":
                typer.echo("Success", err=True)
            typer.echo(json.dumps({} if defect == "payload" else payload))
        else:
            typer.echo(
                json.dumps(payload)
                if defect == "raw-human"
                else ("Name: Acme" if payload else "No records")
            )

    if nested:
        parent = typer.Typer(add_completion=False)
        parent.add_typer(app, name="contacts")
        return parent
    return app


def contract():
    return Contract(
        "data",
        OPTIONS,
        "Test fixture data command, never a production Dinero resource.",
        tuple(
            Case(("--scenario", key), payload, ("Name: Acme" if payload else "No records",))
            for key, payload in PAYLOADS.items()
        )
        + (Case(("--scenario", "error"), ERROR, ("Bad request",), 3, "api"),),
        {
            kind: "Synthetic command has no input/auth/transport boundary."
            for kind in ("validation", "authentication", "transport")
        },
    )


def test_positive_data_shapes_and_recursive_discovery():
    assert "1 data commands" in check(sample(), {(): contract()})
    app = sample(nested=True)
    registry = {
        (): Contract("group", frozenset(), "Top-level namespace"),
        ("contacts",): Contract("group", frozenset(), "Resource namespace"),
        ("contacts", "show"): contract(),
    }
    assert set(discover(app)) == set(registry)
    assert "3 command nodes" in check(app, registry)


@pytest.mark.parametrize(
    "defect,rule",
    [
        ("noise", "OUT-002"),
        ("ansi", "OUT-002"),
        ("raw-human", "OUT-001"),
        ("error-stdout", "ERR-001"),
        ("wrong-status", "ERR-001"),
        ("exit", "ERR-001"),
        ("payload", "OUT-002"),
        ("stderr", "OUT-002"),
        ("secret", "SEC-001"),
    ],
)
def test_defective_runtime_is_rejected(defect, rule):
    with pytest.raises(AssertionError, match=rule):
        check(sample(defect), {(): contract()}, secrets=(SECRET,))


@pytest.mark.parametrize(
    "change,rule",
    [
        ({"options": frozenset()}, "option inventory"),
        ({"reason": ""}, "rationale"),
        ({"cases": ()}, "executable cases"),
        ({"kind": "group"}, "group classification"),
        ({"excluded_failures": {}}, "failure matrix"),
        ({"excluded_failures": {"api": "excluded"}}, "both covered and excluded"),
        ({"excluded_failures": {"transport": ""}}, "rationale"),
    ],
)
def test_registry_contract_cannot_silently_weaken(change, rule):
    with pytest.raises(AssertionError, match=rule):
        check(sample(), {(): replace(contract(), **change)})


def test_missing_json_option_is_rejected():
    app = typer.Typer(add_completion=False)

    @app.command()
    def broken():
        typer.echo("Acme")

    with pytest.raises(AssertionError, match="requires --json"):
        check(app, {(): replace(contract(), options=frozenset())})


@pytest.mark.parametrize("registry", [{}, {("renamed",): contract()}])
def test_unregistered_or_renamed_commands_fail(registry):
    with pytest.raises(AssertionError, match="registry differs"):
        check(sample(), registry)


@pytest.mark.parametrize("value", ["{} {}", "NaN", '{"x": 1, "x": 2}', "\x1b[31m{}"])
def test_strict_decoder(value):
    with pytest.raises(AssertionError, match="OUT-002"):
        decode(value)


def test_external_effects_are_blocked():
    with pytest.raises(AssertionError, match="external I/O"):
        socket.create_connection(("example.invalid", 443))
    with pytest.raises(AssertionError, match="external I/O"):
        subprocess.run(["dinero", "invoices", "book", "never"], check=True)


def test_control_requires_actual_output_and_cases():
    app = typer.Typer(add_completion=False)

    @app.command()
    def version():
        typer.echo("1.0")

    control = Contract("control", frozenset(), "Build version only", (Case((), human=("1.0",)),))
    assert "0 data commands" in check(app, {(): control})
    with pytest.raises(AssertionError, match="human output"):
        check(app, {(): replace(control, cases=(Case((), human=("missing",)),))})
