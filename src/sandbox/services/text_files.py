"""Plain-text files in any stored encoding, served to the viewer as UTF-8.

Stored text files do not all arrive as UTF-8. A document source that reads a
SQL Server ``nvarchar`` column gets UTF-16LE (Kızılay's QDMS ``.txt`` files
start with the ``FF FE`` byte-order mark), Notepad writes a UTF-8 BOM, and
older Turkish Windows tools write Windows-1254. The viewer route used to label
every one of them ``charset=utf-8`` and send the bytes unchanged, so the
browser decoded UTF-16 as UTF-8 and showed "D o k � m a n" for "Doküman".

The rule: find the real encoding from the bytes, then give the viewer UTF-8
text labelled ``charset=utf-8``. A download keeps the original bytes but is
labelled with their real charset.
"""
from __future__ import annotations

import codecs

# Media type per text extension (the charset is added by the callers).
_TEXT_TYPES = {
    ".txt": "text/plain",
    ".md": "text/plain",
    ".log": "text/plain",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".xml": "text/xml",
}

# Python codec name -> the charset name browsers know.
_CHARSET_LABELS = {
    "utf-8": "utf-8",
    "utf-8-sig": "utf-8",
    "utf-16": "utf-16",
    "utf-16-le": "utf-16le",
    "utf-16-be": "utf-16be",
    "utf-32": "utf-32",
    "cp1254": "windows-1254",
    "latin-1": "iso-8859-1",
}

# How much of a file the no-BOM UTF-16 check looks at.
_SAMPLE = 8192


def is_text_file(ext: str) -> bool:
    return ext.lower() in _TEXT_TYPES


def _utf16_without_bom(data: bytes) -> str | None:
    """UTF-16 with no BOM shows as a zero byte beside most Latin letters:
    at the odd offsets for little-endian, at the even ones for big-endian."""
    sample = data[: _SAMPLE - (_SAMPLE % 2)]
    if len(sample) < 4:
        return None
    if len(sample) % 2:
        sample = sample[:-1]
    pairs = len(sample) // 2
    even_zero = sum(1 for b in sample[0::2] if b == 0) / pairs
    odd_zero = sum(1 for b in sample[1::2] if b == 0) / pairs
    if odd_zero >= 0.3 and even_zero < 0.05:
        candidate = "utf-16-le"
    elif even_zero >= 0.3 and odd_zero < 0.05:
        candidate = "utf-16-be"
    else:
        return None
    try:
        codecs.getincrementaldecoder(candidate)("strict").decode(sample, final=False)
    except UnicodeDecodeError:
        return None
    return candidate


def _is_utf8(data: bytes) -> bool:
    # final=False: a sample may end inside a multi-byte character.
    try:
        codecs.getincrementaldecoder("utf-8")("strict").decode(data, final=False)
    except UnicodeDecodeError:
        return False
    return True


def detect_encoding(data: bytes) -> str:
    """The Python codec that reads ``data`` (a whole file or its start)."""
    # UTF-32 before UTF-16: the UTF-32LE BOM begins with the UTF-16LE one.
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return "utf-32"
    if data.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    utf16 = _utf16_without_bom(data)
    if utf16:
        return utf16
    if _is_utf8(data):
        return "utf-8"
    try:
        data.decode("cp1254")
        return "cp1254"
    except UnicodeDecodeError:
        return "latin-1"  # decodes any byte string


def charset_label(encoding: str) -> str:
    return _CHARSET_LABELS.get(encoding, encoding)


def decode_text(data: bytes) -> str:
    text = data.decode(detect_encoding(data), errors="replace")
    return text[1:] if text.startswith("﻿") else text


def viewer_text(data: bytes, ext: str) -> tuple[bytes, str]:
    """A text file's body and media type for the viewer: always UTF-8."""
    media = _TEXT_TYPES.get(ext.lower(), "text/plain")
    return decode_text(data).encode("utf-8"), f"{media}; charset=utf-8"


def download_media_type(head: bytes, ext: str) -> str:
    """The media type for a text file's original bytes, naming their real charset."""
    media = _TEXT_TYPES.get(ext.lower(), "text/plain")
    return f"{media}; charset={charset_label(detect_encoding(head))}"
