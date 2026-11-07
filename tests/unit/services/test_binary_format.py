"""Binary column values: readable by default, the exact bytes on request."""
import base64

from sandbox.services.rest_api import BINARY_MARKER, SQLExecutionRequest, _make_json_safe

DATA = bytes(range(256))


def test_default_keeps_text_in_a_binary_column_readable():
    assert _make_json_safe(b"plain text") == "plain text"
    turkish = "AMAÇ\nBu prosedürün amacı,\tTürkiye Kızılay\r\nsatır\x0biki\x0c"
    assert _make_json_safe(turkish.encode("utf-8")) == turkish
    assert _make_json_safe(b"") == ""
    assert isinstance(_make_json_safe(DATA), str)


# The first bytes of real files from a varbinary document column.
DOCX = b"PK\x03\x04\x14\x00\x00\x00\x08\x00Hz=]\xd5\\\xd1j[Content_Types].xml" + bytes(range(256)) * 200
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n5 0 obj\n<</Type/Page>>\n" + bytes(range(128, 256)) * 400
OLE_DOC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00\x3e\x00\x03\xfe\xff" * 9000
# Valid UTF-8 from start to end, but still a file: the control characters give it away.
ZIP_ALL_ASCII = b"PK\x03\x04\x14\x00" + b"word/document.xml" * 100


def test_a_stored_file_is_named_not_decoded_into_control_characters():
    for file in (DOCX, PDF, OLE_DOC, ZIP_ALL_ASCII):
        assert _make_json_safe(file) == f"[binary, {len(file)} bytes]"


def test_a_short_binary_value_shows_its_bytes_as_hex():
    rowversion = b"\x00\x00\x00\x00\x00\x00\x07\xd1"
    assert _make_json_safe(rowversion) == "0x00000000000007d1"
    # Valid UTF-8, yet not text: NULs and a control byte.
    assert _make_json_safe(b"\x00\x00\x00\x00\x00\x00\x07A") == "0x0000000000000741"
    sha256 = bytes(range(128, 160))
    assert _make_json_safe(sha256) == "0x" + sha256.hex()


def test_the_longest_hex_and_the_shortest_named_value_meet_at_32_bytes():
    assert _make_json_safe(b"\xff" * 32) == "0x" + "ff" * 32
    assert _make_json_safe(b"\xff" * 33) == "[binary, 33 bytes]"


def test_a_sample_row_carries_the_label_and_keeps_its_other_columns():
    row = {"DOSYA_ADI": "PRS.042_43.docx", "BOYUT_BYTE": len(DOCX), "ICERIK": DOCX, "METIN": "AMAÇ"}
    out = _make_json_safe(row)
    assert out == {
        "DOSYA_ADI": "PRS.042_43.docx",
        "BOYUT_BYTE": len(DOCX),
        "ICERIK": f"[binary, {len(DOCX)} bytes]",
        "METIN": "AMAÇ",
    }


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
