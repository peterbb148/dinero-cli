"""Non-interactive configuration commands using common services and output."""

import sys
from pathlib import Path
from typing import Annotated

import typer
from pydantic import SecretStr

from dinero_cli.config import Settings, load_settings, save_setting, setting_key
from dinero_cli.errors import CLIError
from dinero_cli.output import emit
from dinero_cli.secrets import SecretStore
from dinero_cli.storage import check_private

FIELDS = ", ".join(name.replace("_", "-") for name in Settings.model_fields)
app = typer.Typer(no_args_is_help=True, help=f"Inspect or change local public settings: {FIELDS}.")
Json = Annotated[bool, typer.Option("--json", help="Write one JSON document.")]


@app.command("list")
def list_config(json_output: Json = False) -> None:
    """Show resolved public settings; credentials are never included."""
    settings = load_settings()
    emit(settings.model_dump(), json_mode=json_output or settings.output == "json")


@app.command("get")
def get_config(key: str, json_output: Json = False) -> None:
    """Show one resolved public setting, for example organization."""
    name = setting_key(key)
    settings = load_settings()
    emit({name: getattr(settings, name)}, json_mode=json_output or settings.output == "json")


@app.command("set")
def set_config(key: str, value: str, json_output: Json = False) -> None:
    """Change one saved public setting. Secrets must use set-client-secret."""
    settings = load_settings()
    result = save_setting(key, value)
    emit(result, json_mode=json_output or result.get("output", settings.output) == "json")


@app.command("set-client-secret")
def set_client_secret(
    input_file: Annotated[str, typer.Option("--input", help="Private UTF-8 file, or - for stdin.")],
    json_output: Json = False,
) -> None:
    """Change the stored OAuth client secret without placing its value in arguments."""
    settings = load_settings()
    store = SecretStore(settings)
    try:
        if input_file == "-":
            value = sys.stdin.read()
        else:
            path = Path(input_file)
            check_private(path)
            value = path.read_text(encoding="utf-8")
    except UnicodeError as error:
        raise CLIError("Client secret input must be UTF-8.") from error
    value = value.rstrip("\r\n")
    if not value.strip() or "\x00" in value or "\n" in value or "\r" in value:
        raise CLIError("Client secret input must contain one nonempty line.")
    with store.transaction() as transaction:
        transaction.state.client_secret = SecretStr(value)
        transaction.save()
    emit({"client_secret_stored": True}, json_mode=json_output or settings.output == "json")
