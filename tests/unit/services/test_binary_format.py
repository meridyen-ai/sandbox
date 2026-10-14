"""Binary column values: text by default (as always), the exact bytes on request."""
import base64

from sandbox.services.rest_api import BINARY_MARKER, SQLExecutionRequest, _make_json_safe

DATA = bytes(range(256))


def test_default_keeps_the_old_text_decoding():
    assert _make_json_safe(b"plain text") == "plain text"
    assert isinstance(_make_json_safe(DATA), str)


def test_base64_returns_the_bytes_with_a_marker():
    for value in (DATA, bytearray(DATA), memoryview(DATA)):
        out = _make_json_safe(value, "base64")
        assert set(out) == {BINARY_MARKER}
        assert base64.b64decode(out[BINARY_MARKER]) == DATA


def test_rows_and_nested_values_carry_the_format():
    row = {"id": 1, "file": DATA, "parts": [b"ab"], "name": "x"}
    out = _make_json_safe(row, "base64")
    assert out["id"] == 1 and out["name"] == "x"
    assert base64.b64decode(out["file"][BINARY_MARKER]) == DATA
    assert out["parts"] == [{BINARY_MARKER: "YWI="}]


def test_the_request_option_defaults_to_text():
    assert SQLExecutionRequest(query="SELECT 1").context.binary_format == "text"
    assert SQLExecutionRequest(query="SELECT 1", context={"binary_format": "base64"}).context.binary_format == "base64"
