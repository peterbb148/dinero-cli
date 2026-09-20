"""Authentication commands expose status only, never token response data."""

from pathlib import Path
from typing import Annotated

import typer

from dinero_cli.auth import AuthService
from dinero_cli.commands.config import Json
from dinero_cli.config import load_settings
from dinero_cli.oauth_callback import collect
from dinero_cli.output import emit
from dinero_cli.payloads import read_object
from dinero_cli.personal import parse_credentials
from dinero_cli.storage import check_private

app = typer.Typer(
    no_args_is_help=True,
    help="Authorize via Visma Connect or personal integration; inspect status.",
)


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
    """Remove tokens and personal credentials; preserve the Visma secret and server consent."""
    settings = load_settings()
    emit(AuthService(settings).logout(), json_mode=json_output or settings.output == "json")


@app.command("login-personal")
def login_personal(
    input_file: Annotated[
        str, typer.Option("--input", help="Private JSON credentials file, or - for stdin.")
    ],
    organization: Annotated[
        str | None, typer.Option(help="Organization matching the API key.")
    ] = None,
    json_output: Json = False,
) -> None:
    """Authorize using Dinero personal client credentials and an organization API key."""
    settings = load_settings(organization=organization)
    if input_file != "-":
        check_private(Path(input_file))
    personal = parse_credentials(read_object(input_file))
    result = AuthService(settings).login_personal(personal)
    emit(result, json_mode=json_output or settings.output == "json")
