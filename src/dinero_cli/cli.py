"""Minimal executable CLI foundation; API commands are separate issues."""

import typer

from dinero_cli._version import VERSION

app = typer.Typer(no_args_is_help=True, help="Dinero CLI. Discover commands using --help.")


@app.callback(invoke_without_command=True)
def root(version: bool = typer.Option(False, "--version", help="Show the build version.")) -> None:
    """Expose build identity without credentials or network access."""
    if version:
        typer.echo(VERSION)
        raise typer.Exit()


def main() -> None:
    """Run the command-line interface."""
    app()
