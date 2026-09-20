"""Wire-level resource commands: options, payload fidelity, isolation and one request."""

import json
from urllib.parse import parse_qsl

import httpx
import pytest
from typer.testing import CliRunner

from dinero_cli.auth import Credentials
from dinero_cli.cli import app
from dinero_cli.client import APIClient
from dinero_cli.commands import resources
from dinero_cli.config import Settings

GUID = "cdb485f3-a188-48b1-8d40-f6c8014c9f21"
CONTACT = {
    "Name": "Æble",
    "CountryKey": "DK",
    "IsPerson": False,
    "IsMember": False,
    "UseCvr": False,
}
PRODUCT = {"BaseAmountValue": 20.5, "Quantity": 2, "AccountNumber": 1000, "Unit": "hours"}
CONTACT_ARGS = [
    "--name",
    "Æble",
    "--country-key",
    "DK",
    "--no-is-person",
    "--no-is-member",
    "--no-use-cvr",
]
PRODUCT_ARGS = [
    "--base-amount-value",
    "20.5",
    "--quantity",
    "2",
    "--account-number",
    "1000",
    "--unit",
    "hours",
]


@pytest.fixture
def wire(monkeypatch, tmp_path):
    monkeypatch.setenv("DINERO_CONFIG_DIR", str(tmp_path))
    for key in Settings.model_fields:
        monkeypatch.delenv("DINERO_" + key.upper(), raising=False)
    calls = []

    class Auth:
        def credentials(self):
            return Credentials("secret", ("secret",))

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"Items": [{"Name": "Æble"}], "Next": "preserved"})

    monkeypatch.setattr(
        resources,
        "APIClient",
        lambda settings: APIClient(settings, auth=Auth(), transport=httpx.MockTransport(respond)),
    )
    return CliRunner(), calls


@pytest.mark.parametrize(
    "resource,body,options",
    [("contacts", CONTACT, CONTACT_ARGS), ("products", PRODUCT, PRODUCT_ARGS)],
)
@pytest.mark.parametrize(
    "verb,method",
    [("list", "GET"), ("get", "GET"), ("create", "POST"), ("update", "PUT"), ("delete", "DELETE")],
)
def test_dedicated_requests(wire, resource, body, options, verb, method):
    runner, calls = wire
    args = [resource, verb]
    if verb in ("get", "update", "delete"):
        args.append(GUID)
    if verb in ("create", "update"):
        args.extend(options)
    result = runner.invoke(app, [*args, "--organization", "456", "--json"])
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {"Items": [{"Name": "Æble"}], "Next": "preserved"}
    assert len(calls) == 1
    req = calls[0]
    assert req.method == method
    suffix = "/" + GUID if verb in ("get", "update", "delete") else ""
    assert req.url.path == f"/v1/456/{resource}{suffix}"
    assert not req.url.query
    assert (json.loads(req.content) if req.content else None) == (
        body if verb in ("create", "update") else None
    )


def test_organizations_without_context(wire):
    runner, calls = wire
    assert (
        runner.invoke(app, ["organizations", "list", "--fields", "id,name", "--json"]).exit_code
        == 0
    )
    assert calls[0].url.path == "/v1/organizations"
    assert parse_qsl(calls[0].url.query.decode()) == [("fields", "id,name")]


@pytest.mark.parametrize("resource", ["contacts", "products"])
@pytest.mark.parametrize("flag,value", [("--deleted-only", "true"), ("--no-deleted-only", "false")])
def test_query_options_are_exact_and_single_page(wire, resource, flag, value):
    runner, calls = wire
    args = [
        resource,
        "list",
        "--organization",
        "456",
        "--fields",
        "Name,Email",
        "--query-filter",
        "Name eq 'Æ & +'",
        "--changes-since",
        "2026-01-01",
        flag,
        "--page",
        "3",
        "--page-size",
        "1000",
    ]
    if resource == "products":
        args += ["--free-text-search", "Æ & +"]
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.stderr
    assert len(calls) == 1
    query = dict(parse_qsl(calls[0].url.query.decode()))
    assert query == {
        "fields": "Name,Email",
        "queryFilter": "Name eq 'Æ & +'",
        "changesSince": "2026-01-01",
        "deletedOnly": value,
        "page": "3",
        "pageSize": "1000",
        **({"freeTextSearch": "Æ & +"} if resource == "products" else {}),
    }


@pytest.mark.parametrize("resource,body", [("contacts", CONTACT), ("products", PRODUCT)])
@pytest.mark.parametrize("verb", ["create", "update"])
@pytest.mark.parametrize("stdin", [False, True])
def test_json_payload_unknown_fields_and_no_defaults(wire, tmp_path, resource, body, verb, stdin):
    runner, calls = wire
    body = {**body, "FutureField": {"items": [1, None]}, "Email": None}
    source = json.dumps(body)
    path = tmp_path / "body.json"
    path.write_text(source)
    args = [
        resource,
        verb,
        *([GUID] if verb == "update" else []),
        "--organization",
        "456",
        "--input",
        "-" if stdin else str(path),
        "--json",
    ]
    result = runner.invoke(app, args, input=source if stdin else None)
    assert result.exit_code == 0, result.stderr
    assert json.loads(calls[0].content) == body


@pytest.mark.parametrize(
    "args,input_value",
    [
        (["contacts", "create", "--input", "-", "--name", "Æble"], json.dumps(CONTACT)),
        (["contacts", "create", "--input", "-"], "{}"),
        (["products", "create", "--input", "-"], json.dumps({**PRODUCT, "Quantity": "2"})),
        (["contacts", "list", "--deleted-only", "--no-deleted-only"], None),
        (["contacts", "list", "--page-size", "1001"], None),
        (["products", "list", "--page", "-1"], None),
        (["contacts", "get", "../invoices"], None),
        (["contacts", "list"], None),
    ],
)
def test_invalid_inputs_do_not_send(wire, args, input_value):
    runner, calls = wire
    result = runner.invoke(app, [*args, "--json"], input=input_value)
    assert result.exit_code == 2, result.stderr
    assert not result.stdout and not calls


def test_contact_true_flags_and_payload_collision(wire):
    runner, calls = wire
    args = [
        "contacts",
        "create",
        "--name",
        "Æble",
        "--country-key",
        "DK",
        "--is-person",
        "--is-member",
        "--use-cvr",
        "--organization",
        "123",
        "--json",
    ]
    assert runner.invoke(app, args).exit_code == 0
    assert json.loads(calls[0].content)["IsPerson"] is True
    calls.clear()
    assert runner.invoke(app, [*args, "--no-is-person"]).exit_code == 2
    assert not calls
