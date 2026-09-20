"""Executable CLI output contracts tied to the actual Typer command tree."""

import json
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from typing import Any, Literal

import typer
from typer.main import get_command
from typer.testing import CliRunner

Path = tuple[str, ...]
FAILURES = {"validation", "authentication", "api", "transport"}


@dataclass(frozen=True)
class Case:
    """One deterministic invocation; setup replaces the command's external boundary."""

    args: tuple[str, ...]
    expected: Any = None
    human: tuple[str, ...] = ()
    exit_code: int = 0
    failure: str | None = None
    setup: Callable[[], AbstractContextManager] = nullcontext


@dataclass(frozen=True)
class Contract:
    """Reviewed classification, option inventory and runtime evidence for one command."""

    kind: Literal["group", "data", "control"]
    options: frozenset[str]
    reason: str
    cases: tuple[Case, ...] = ()
    excluded_failures: Mapping[str, str] = field(default_factory=dict)


def discover(app: typer.Typer) -> dict[Path, Any]:
    """Discover every node, including groups and a collapsed single-command root."""
    found: dict[Path, Any] = {}

    def visit(command: Any, path: Path) -> None:
        found[path] = command
        if hasattr(command, "list_commands"):
            with command.make_context("dinero", [], resilient_parsing=True) as ctx:
                for name in command.list_commands(ctx):
                    visit(command.get_command(ctx, name), (*path, name))

    visit(get_command(app), ())
    return found


def decode(text: str) -> Any:
    """Require one strict JSON document without terminal escapes or duplicate keys."""
    assert "\x1b" not in text, "OUT-002: ANSI in JSON"

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            assert key not in result, "OUT-002: duplicate JSON key"
            result[key] = value
        return result

    def invalid(value: str) -> None:
        raise AssertionError(f"OUT-002: invalid JSON constant {value}")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    except ValueError as error:
        raise AssertionError("OUT-002: expected exactly one JSON document") from error


def check(
    app: typer.Typer,
    registry: Mapping[Path, Contract],
    secrets: tuple[str, ...] = (),
) -> str:
    """Check registered cases; callers must isolate HOME and block external effects."""
    commands = discover(app)
    assert commands.keys() == registry.keys(), "CMD-001: command registry differs from discovery"
    runner = CliRunner()
    for path, command in commands.items():
        contract = registry[path]
        assert contract.reason.strip(), "CMD-001: classification requires a rationale"
        options = frozenset(
            option
            for param in command.params
            for option in (*param.opts, *getattr(param, "secondary_opts", []))
            if option.startswith("-")
        )
        assert options == contract.options, f"CMD-001: option inventory changed: {path}"
        help_result = runner.invoke(app, [*path, "--help"], color=False)
        assert help_result.exit_code == 0 and "Usage:" in help_result.stdout, "CMD-001: help"
        if contract.kind == "group":
            assert hasattr(command, "list_commands"), "CMD-001: group classification on leaf"
            exercised = {arg for case in contract.cases for arg in case.args}
            assert options <= exercised, "CMD-001: group controls lack executable cases"
        else:
            assert contract.cases, "CMD-001: missing executable cases"
        if contract.kind == "data":
            assert "--json" in options, "OUT-002: data command requires --json"
            assert any(not c.exit_code for c in contract.cases), "OUT-001: missing success"
            assert any(c.exit_code for c in contract.cases), "ERR-001: missing error case"
            covered = {c.failure for c in contract.cases if c.exit_code}
            excluded = contract.excluded_failures
            assert all(excluded.values()), "ERR-001: exclusions require rationale"
            assert covered.isdisjoint(excluded), "ERR-001: failure both covered and excluded"
            assert covered | set(excluded) == FAILURES, "ERR-001: incomplete failure matrix"
        for case in contract.cases:
            for machine in (False, True) if contract.kind == "data" else (False,):
                # Exercise redirected output both with ordinary and forced colour environments.
                for force_color in (False, True):
                    env = {"TERM": "dumb", "NO_COLOR": "1"}
                    if force_color:
                        env = {"TERM": "xterm-256color", "FORCE_COLOR": "1", "NO_COLOR": ""}
                    with case.setup():
                        result = runner.invoke(
                            app,
                            [*path, *case.args, *(["--json"] if machine else [])],
                            env=env,
                            color=force_color,
                        )
                    assert result.exit_code == case.exit_code, "ERR-001: unexpected exit code"
                    for secret in secrets:
                        assert secret not in result.stdout + result.stderr, "SEC-001: secret leaked"
                    if case.exit_code:
                        assert not result.stdout, "ERR-001: error wrote stdout"
                        assert result.stderr.strip(), "ERR-001: missing stderr"
                        if machine:
                            error = decode(result.stderr)
                            assert isinstance(error, dict), "ERR-001: error must be an object"
                            assert set(error) == {"error", "status", "message", "details"}
                            assert error["error"] is True and isinstance(error["message"], str)
                            assert error["status"] is None or type(error["status"]) is int
                            assert error == case.expected, "ERR-001: error payload differs"
                        else:
                            assert case.human and all(t in result.stderr for t in case.human)
                    else:
                        assert not result.stderr, "OUT-002: success wrote stderr"
                        if machine:
                            assert json.dumps(decode(result.stdout), sort_keys=True) == json.dumps(
                                case.expected, sort_keys=True
                            ), "OUT-002: payload differs"
                        else:
                            assert case.human and all(t in result.stdout for t in case.human), (
                                "OUT-001: missing meaningful human output"
                            )
                            if contract.kind == "data" and isinstance(case.expected, (list, dict)):
                                try:
                                    json.loads(result.stdout)
                                except ValueError:
                                    pass
                                else:
                                    raise AssertionError("OUT-001: human output is only JSON")
    count = sum(c.kind == "data" for c in registry.values())
    return f"CLI contracts: {len(commands)} command nodes, {count} data commands"
