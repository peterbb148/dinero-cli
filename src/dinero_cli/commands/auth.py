"""Authentication commands expose status only, never token response data."""

from pathlib import Path
from typing import Annotated

import typer

from dinero_cli.auth import AuthService
from dinero_cli.commands.config import Json
from dinero_cli.config import load_settings
from dinero_cli.oauth_callback import collect
from dinero_cli.output import emit

app = typer.Typer(no_args_is_help=True, help="Authorize via Visma Connect or inspect local status.")


@app.command()
def login(
    json_output: Json = False,
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="Do not launch a browser; write a private consent link."),
    ] = False,
    authorization_url_file: Annotated[
        Path | None, typer.Option(help="Write the consent URL to a private file.")
    ] = None,
    callback_file: Annotated[
        Path | None,
        typer.Option(help="Read a new private callback form file from your HTTPS handler."),
    ] = None,
    timeout: Annotated[
        float, typer.Option(min=1, max=1800, help="Seconds allowed for browser consent.")
    ] = 300,
) -> None:
    """Replace local authorization after explicit browser consent; no organization is needed."""
    settings = load_settings()
    service = AuthService(settings)
    result = service.login(
        lambda url, state: collect(
            settings,
            url,
            state,
            timeout=timeout,
            no_browser=no_browser,
            url_file=authorization_url_file,
            callback_file=callback_file,
        )
    )
    emit(result, json_mode=json_output or settings.output == "json")


@app.command()
def status(json_output: Json = False) -> None:
    """Inspect authorization metadata without sending requests or refreshing tokens."""
    settings = load_settings()
    emit(AuthService(settings).status(), json_mode=json_output or settings.output == "json")


@app.command()
def logout(json_output: Json = False) -> None:
    """Remove local tokens; preserve the client secret and server-side authorization."""
    settings = load_settings()
    emit(AuthService(settings).logout(), json_mode=json_output or settings.output == "json")
