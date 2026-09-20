"""Strict payload input, before any credential or network operation."""

import io

import pytest

from dinero_cli.errors import CLIError
from dinero_cli.payloads import read_object


def test_file_and_stdin_preserve_complex_payload(tmp_path, monkeypatch):
    raw = '{"Name":"Åse","Lines":[{"Quantity":0,"Price":1.5}],"Unknown":null}'.encode()
    path = tmp_path / "payload.json"
    path.write_bytes(raw)
    expected = {"Name": "Åse", "Lines": [{"Quantity": 0, "Price": 1.5}], "Unknown": None}
    assert read_object(str(path)) == expected
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8"))
    assert read_object("-") == expected


@pytest.mark.parametrize(
    "raw",
    [
        b"invalid sentinel-secret",
        b"\xff",
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b"[1]",
        b"null",
        b"42",
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_invalid_payload_is_sanitized(tmp_path, raw):
    path = tmp_path / "payload.json"
    path.write_bytes(raw)
    with pytest.raises(CLIError) as failure:
        read_object(str(path))
    assert failure.value.code == 2 and "sentinel" not in str(failure.value)


def test_missing_file_is_an_explicit_io_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_object(str(tmp_path / "missing"))


def test_lone_surrogates_in_json_keys_and_values_are_rejected(tmp_path):
    for raw in (b'{"value":"\\ud800"}', b'{"\\udfff":"value"}'):
        path = tmp_path / "payload.json"
        path.write_bytes(raw)
        with pytest.raises(CLIError, match="UTF-8 JSON"):
            read_object(str(path))
