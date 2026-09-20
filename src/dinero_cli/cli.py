"""CLI boundary: shared errors and command registration, with no storage logic."""

import os
import sys
from collections.abc import Sequence
from typing import Any, TextIO, cast

import typer
from typer._click.exceptions import ClickException
from typer.core import Abort, TyperGroup
from typer.main import get_command

from dinero_cli._version import VERSION
from dinero_cli.commands.api import app as api_app
from dinero_cli.commands.auth import app as auth_app
from dinero_cli.commands.config import app as config_app
from dinero_cli.commands.contacts import app as contacts_app
from dinero_cli.commands.organizations import app as organizations_app
from dinero_cli.commands.products import app as products_app
from dinero_cli.config import saved_values
from dinero_cli.errors import CLIError
from dinero_cli.output import OutputClosed, PipeWriter, emit_error, silence_closed_pipe


def error_json_mode(argv: Sequence[str]) -> bool:
    """Select error presentation without letting broken configuration hide the error itself."""
    options = argv[: argv.index("--")] if "--" in argv else argv
    if "--json" in options:
        return True
    if "DINERO_OUTPUT" in os.environ:
        return os.environ["DINERO_OUTPUT"] == "json"
    try:
        return saved_values().get("output") == "json"
    except (CLIError, OSError):
        return False  # No readable preference; the error still fails, in default human mode.


def fail(error: CLIError, *, json_mode: bool) -> None:
    """Render a failure once; a closed diagnostic pipe is itself an output failure."""
    try:
        emit_error(error, json_mode=json_mode)
    except (OSError, UnicodeError, OutputClosed):
        silence_closed_pipe(sys.stderr)
        raise SystemExit(5)
    raise SystemExit(error.code)


class CommandGroup(TyperGroup):
    """Keep parser and service failures in the same safe output contract."""

    def make_context(self, *args: Any, **kwargs: Any) -> Any:
        """Apply the same quiet output policy to parser-generated help."""
        try:
            return super().make_context(*args, **kwargs)
        except BrokenPipeError as error:
            silence_closed_pipe(sys.stdout)
            raise OutputClosed() from error

    def invoke(self, ctx: Any) -> Any:
        """Handle interruption and broken output before Typer converts or prints them."""
        try:
            return super().invoke(ctx)
        except (KeyboardInterrupt, EOFError) as error:
            raise CLIError("Input was interrupted.", code=130) from error
        except BrokenPipeError as error:
            silence_closed_pipe(sys.stdout)
            raise OutputClosed() from error

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
                if result == 130:
                    raise CLIError("Input was interrupted.", code=130)
                raise SystemExit(result)
            return result
        except CLIError as failure:
            error = failure
        except ClickException:
            error = CLIError("Invalid arguments. Use --help for command syntax.")
        except Abort:
            error = CLIError("Input was interrupted.", code=130)
        except OutputClosed:
            raise SystemExit(5)
        except OSError:
            error = CLIError("Unable to read or write local state or output.", code=5)
        fail(error, json_mode=error_json_mode(argv))


app = typer.Typer(
    cls=CommandGroup,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="Dinero CLI. Discover commands using --help.",
)
app.add_typer(config_app, name="config")
app.add_typer(auth_app, name="auth")
app.add_typer(api_app, name="api")
app.add_typer(organizations_app, name="organizations")
app.add_typer(contacts_app, name="contacts")
app.add_typer(products_app, name="products")


@app.callback(invoke_without_command=True)
def root(version: bool = typer.Option(False, "--version", help="Show the build version.")) -> None:
    """Expose build identity without credentials or network access."""
    if version:
        typer.echo(VERSION)
        raise typer.Exit()


def main() -> None:
    """Run the process entrypoint with UTF-8 streams and a sanitized last-resort hook."""

    def unexpected(kind: type[BaseException], value: BaseException, traceback: Any) -> None:
        # Python's exception hook preserves its nonzero process exit without catching
        # arbitrary provider/programming exceptions or exposing their values/tracebacks.
        fail(
            CLIError("Unexpected internal failure.", code=1),
            json_mode=error_json_mode(sys.argv[1:]),
        )

    sys.excepthook = unexpected
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="strict")
    sys.stdout = cast(TextIO, PipeWriter(sys.stdout))
    sys.stderr = cast(TextIO, PipeWriter(sys.stderr))
    # Calling the generated command avoids Typer.__call__ replacing the safe process hook.
    get_command(app)()
