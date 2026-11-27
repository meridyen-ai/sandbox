"""Text files reach the viewer as UTF-8 whatever encoding they were stored in.

Kızılay's QDMS documents without a Word/PDF original are stored as ``.txt``
written by SQL Server: a UTF-16LE byte-order mark plus UTF-16LE text. The
viewer route labelled those bytes ``charset=utf-8`` and sent them unchanged,
so the browser showed "D o k � m a n  N o" for "Doküman No" (2026-11-27,
YNT.001 in a customer demo).
"""
import codecs

import pytest

from sandbox.services.text_files import (
    decode_text,
    detect_encoding,
    is_text_file,
    viewer_text,
)

TURKISH = "Doküman No YNT.001\nKızılay Kurumsal Mevzuat Hazırlama Yönetmeliği — ğüşıöç ĞÜŞİÖÇ\n"


def stored(text: str, encoding: str, bom: bytes = b"") -> bytes:
    return bom + text.encode(encoding)


CASES = {
    # What the QDMS source query writes: 0xFFFE + CAST(nvarchar AS varbinary).
    "utf-16le with BOM (SQL Server)": stored(TURKISH, "utf-16-le", codecs.BOM_UTF16_LE),
    "utf-16be with BOM": stored(TURKISH, "utf-16-be", codecs.BOM_UTF16_BE),
    "utf-16le without BOM": stored(TURKISH, "utf-16-le"),
    "utf-16be without BOM": stored(TURKISH, "utf-16-be"),
    "utf-8": stored(TURKISH, "utf-8"),
    "utf-8 with BOM (Notepad)": stored(TURKISH, "utf-8", codecs.BOM_UTF8),
    "utf-32le with BOM": stored(TURKISH, "utf-32-le", codecs.BOM_UTF32_LE),
    "windows-1254 (Turkish Windows)": stored(TURKISH.replace("—", "-"), "cp1254"),
}


@pytest.mark.parametrize("name", CASES)
def test_every_stored_encoding_reads_back_as_the_same_text(name):
    expected = TURKISH.replace("—", "-") if "1254" in name else TURKISH
    assert decode_text(CASES[name]) == expected


@pytest.mark.parametrize("name", CASES)
def test_the_viewer_gets_utf8_bytes_labelled_utf8(name):
    body, media_type = viewer_text(CASES[name], ".txt")
    assert media_type == "text/plain; charset=utf-8"
    assert not body.startswith(codecs.BOM_UTF8), "a BOM would show as a stray character"
    assert b"\x00" not in body
    assert "Kızılay" in body.decode("utf-8")


def test_the_customer_file_from_the_demo_reads_as_turkish():
    # The first bytes of YNT.001.txt as the sandbox served them on 2026-11-27.
    head = b"\xff\xfeD\x00o\x00k\x00\xfc\x00m\x00a\x00n\x00 \x00N\x00o\x00 \x00"
    body, _ = viewer_text(head, ".txt")
    assert body.decode("utf-8") == "Doküman No "


def test_a_csv_keeps_its_type():
    body, media_type = viewer_text(stored("a;b\nı;ş\n", "utf-16-le", codecs.BOM_UTF16_LE), ".csv")
    assert media_type == "text/csv; charset=utf-8"
    assert body.decode("utf-8") == "a;b\nı;ş\n"


def test_the_download_label_names_the_real_encoding():
    assert detect_encoding(CASES["utf-16le with BOM (SQL Server)"]) == "utf-16"
    assert detect_encoding(CASES["utf-16le without BOM"]) == "utf-16-le"
    assert detect_encoding(CASES["utf-8"]) == "utf-8"
    assert detect_encoding(CASES["utf-8 with BOM (Notepad)"]) == "utf-8-sig"
    assert detect_encoding(CASES["windows-1254 (Turkish Windows)"]) == "cp1254"
    assert detect_encoding(b"") == "utf-8"


def test_plain_ascii_and_empty_files_stay_as_they_are():
    assert decode_text(b"") == ""
    assert decode_text(b"plain ascii\n") == "plain ascii\n"


def test_only_text_types_are_treated_as_text():
    for ext in (".txt", ".md", ".csv", ".tsv", ".log", ".json", ".xml", ".TXT"):
        assert is_text_file(ext)
    for ext in (".pdf", ".docx", ".html", ".png", ""):
        assert not is_text_file(ext)
