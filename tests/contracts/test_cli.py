"""The explicit production registry; add each new command and its fixtures here."""

from pathlib import Path

from api_cases import CONTRACTS as API_CONTRACTS
from auth_cases import CONTRACTS as AUTH_CONTRACTS
from config_cases import CONTRACTS
from typer import completion

from devtools.contracts import Case, Contract, check
from dinero_cli._version import VERSION
from dinero_cli.cli import app

# Completion's shell detection and installation are external boundaries. Its real
# callbacks still execute; neither an actual shell nor the user's rc files are touched.
REGISTRY = {
    **CONTRACTS,
    **AUTH_CONTRACTS,
    **API_CONTRACTS,
    (): Contract(
        kind="group",
        options=frozenset({"--version", "--install-completion", "--show-completion"}),
        reason="Namespace plus build version and Typer shell controls; no API data is returned.",
        cases=(
            Case(("--version",), human=(VERSION,)),
            Case(("--show-completion",), human=("complete", "_COMPLETE")),
            Case(("--install-completion",), human=("completion installed", "restart")),
            Case(("--unknown",), human=("Invalid arguments",), exit_code=2),
        ),
    ),
}


def test_production_command_contracts(monkeypatch):
    monkeypatch.setattr(completion, "_get_shell_name", lambda: "bash")
    monkeypatch.setattr(completion, "install", lambda: ("bash", Path("fixture-completion.sh")))
    report = check(app, REGISTRY, secrets=("contract-access-token", "contract-client-secret"))
    print(report)
    assert report == "CLI contracts: 16 command nodes, 12 data commands"
