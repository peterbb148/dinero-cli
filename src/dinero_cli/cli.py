"""CLI boundary: shared errors and command registration, with no storage logic."""

import sys
from collections.abc import Sequence
from typing import Any

import typer
from typer._click.exceptions import ClickException
from typer.core import Abort, TyperGroup

from dinero_cli._version import VERSION
from dinero_cli.commands.config import app as config_app
from dinero_cli.errors import CLIError
from dinero_cli.output import emit_error


class CommandGroup(TyperGroup):
    """Keep parser and service failures in the same safe output contract."""

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Handle known command failures without echoing sensitive parser input."""
        argv = list(sys.argv[1:] if args is None else args)
        options = argv[: argv.index("--")] if "--" in argv else argv
        json_mode = "--json" in options
        kwargs["standalone_mode"] = False
        error: CLIError
        try:
            result = super().main(
                args=argv,
                prog_name=prog_name,
                complete_var=complete_var,
                windows_expand_args=windows_expand_args,
                **kwargs,
            )
            if isinstance(result, int) and result:
                raise SystemExit(result)
            return result
        except CLIError as failure:
            error = failure
        except ClickException:
            error = CLIError("Invalid arguments. Use --help for command syntax.")
        except Abort:
            error = CLIError("Input was interrupted.", code=130)
        except OSError:
            error = CLIError("Unable to read or write local state or output.", code=5)
        emit_error(error, json_mode=json_mode)
        raise SystemExit(error.code)


app = typer.Typer(
    cls=CommandGroup,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="Dinero CLI. Discover commands using --help.",
)
app.add_typer(config_app, name="config")


@app.callback(invoke_without_command=True)
def root(version: bool = typer.Option(False, "--version", help="Show the build version.")) -> None:
    """Expose build identity without credentials or network access."""
    if version:
        typer.echo(VERSION)
        raise typer.Exit()


def main() -> None:
    """Run the command-line interface."""
    app()
