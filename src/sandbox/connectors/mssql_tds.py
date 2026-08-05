"""
SQL Server (FreeTDS) connection helper.

Every pymssql connection in the sandbox goes through :func:`connect_mssql`.

Why this exists: TDS 7.0 predates per-column collation in the protocol (added in
7.1), so FreeTDS has no way to learn a ``varchar`` column's code page and decodes
it as ISO-8859-1. On a Turkish (CP1254) database that silently mangles text —
``Ş`` (0xDE) arrives as ``Þ``, ``ı`` (0xFD) as ``ý``, ``ğ`` (0xF0) as ``ð`` —
while characters that happen to share a code point with Latin-1 (``Ü``, ``Ö``,
``Ç``) come through fine, which makes the bug easy to miss.

Negotiating TDS 7.4 makes the server send the collation with the column
metadata, so FreeTDS transcodes to the client charset (UTF-8) correctly. Older
servers that cannot speak 7.4 fall back down the version list, and the result is
remembered per target so the probe cost is paid at most once per server.
"""

from __future__ import annotations

import threading
from typing import Any

from sandbox.core.logging import get_logger

logger = get_logger(__name__)

# Modern default: SQL Server 2012+ and Azure SQL. Carries collation, so text in
# non-Latin-1 code pages decodes correctly.
PREFERRED_TDS_VERSION = "7.4"

# Probed in order only if the preferred version is rejected by the server.
# 7.0 stays last as a floor for SQL Server 7.0/2000 — it will still mojibake
# non-Latin-1 text, but a working connection beats no connection.
FALLBACK_TDS_VERSIONS = ("7.3", "7.2", "7.1", "7.0")

# Errors that no other TDS version will fix — bad credentials, unreachable host.
# Retrying those just multiplies the login timeout.
_FATAL_ERROR_FRAGMENTS = (
    "login failed",
    "password",
    "authentication",
    "access denied",
    "not associated with a trusted",
    "invalid object name",
    "unable to connect",
    "connection refused",
    "name or service not known",
    "host is unreachable",
    "network is unreachable",
)

# (server, port, database, user) -> TDS version that worked.
_negotiated: dict[tuple[str, str, str, str], str] = {}
_negotiated_lock = threading.Lock()


# --------------------------------------------------------------------------
# Code page repair
# --------------------------------------------------------------------------
# Negotiating 7.4 is necessary but not sufficient. FreeTDS picks ONE server
# charset per connection — from the server's *default* collation — and does not
# re-derive it per column, so `col COLLATE Turkish_CI_AS` is still decoded with
# the server default. On a CP1252-default server holding a Turkish_CI_AS
# database, every varchar byte comes back decoded as CP1252: 0xDE ('Ş' in
# CP1254) surfaces as 'Þ'. The server itself is right — UNICODE() on that column
# returns 350 (U+015E) — only the client decode is wrong.
#
# So we ask the server for the database's real code page and undo the bad
# decode: re-encode back to the bytes FreeTDS received, then decode with the
# code page that actually applies. NVARCHAR is untouched by all of this (it
# travels as UCS-2), and re-encoding such a value raises, which is exactly the
# signal to leave it alone.
#
# Caveat: a column whose collation differs from its database's would be repaired
# with the database's code page. That is the right call for the overwhelmingly
# common case (whole database in one code page) and still beats today's blanket
# CP1252 assumption.

# Code pages FreeTDS already gets right — no repair, no per-row cost.
_PASSTHROUGH_CODEPAGES = frozenset({0, 1252, 65001})

# Encodings to re-encode through, in order. cp1252 is FreeTDS's assumption;
# latin-1 is the byte-identity fallback for the 0x80-0x9F range where the two
# differ.
_SOURCE_ENCODINGS = ("cp1252", "latin-1")

_DB_CODEPAGE_QUERY = (
    "SELECT CONVERT(int, COLLATIONPROPERTY("
    "CONVERT(nvarchar(128), DATABASEPROPERTYEX(DB_NAME(), 'Collation')), 'CodePage'))"
)


def detect_codepage(conn: Any) -> int:
    """Return the code page of the connected database's collation.

    Returns 1252 (i.e. "no repair needed") if the server cannot answer.
    """
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(_DB_CODEPAGE_QUERY)
            row = cursor.fetchone()
        finally:
            cursor.close()
        codepage = int(row[0]) if row and row[0] is not None else 1252
    except Exception as e:
        logger.warning("codepage_detection_failed", error=str(e)[:200])
        return 1252

    if codepage not in _PASSTHROUGH_CODEPAGES:
        logger.info("codepage_repair_enabled", codepage=codepage)
    return codepage


def needs_repair(codepage: int) -> bool:
    """True if values from this database must be re-decoded."""
    return codepage not in _PASSTHROUGH_CODEPAGES


def repair_text(value: Any, codepage: int) -> Any:
    """Re-decode a mis-decoded varchar value using the database's code page.

    Non-strings, and Unicode values that never went through a code page
    (NVARCHAR), are returned untouched.
    """
    if not isinstance(value, str) or value.isascii():
        # Pure ASCII (or not a string) decodes identically under every code
        # page in play, so there is nothing to repair.
        return value

    codec = f"cp{codepage}"
    for source in _SOURCE_ENCODINGS:
        try:
            raw = value.encode(source)
        except UnicodeEncodeError:
            continue  # real Unicode -> came from NVARCHAR, already correct
        try:
            return raw.decode(codec)
        except (UnicodeDecodeError, LookupError):
            return value
    return value


def repair_row(row: tuple[Any, ...], codepage: int) -> tuple[Any, ...]:
    """Apply :func:`repair_text` to every value in a result row."""
    return tuple(repair_text(v, codepage) for v in row)


def _is_fatal_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(frag in msg for frag in _FATAL_ERROR_FRAGMENTS)


def _cache_key(kwargs: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(kwargs.get("server") or ""),
        str(kwargs.get("port") or ""),
        str(kwargs.get("database") or ""),
        str(kwargs.get("user") or ""),
    )


def connect_mssql(tds_version: str | None = None, **kwargs: Any) -> tuple[Any, str]:
    """Open a pymssql connection, negotiating the highest TDS version the server accepts.

    Args:
        tds_version: Pin a specific version and skip negotiation entirely. Use it
            when a working version has already been persisted for the connection.
        **kwargs: Passed straight through to ``pymssql.connect`` (server, port,
            database, user, password, login_timeout, ...). ``charset`` defaults
            to UTF-8, which is what FreeTDS transcodes *into*.

    Returns:
        ``(connection, negotiated_tds_version)`` — persist the version to skip
        the probe next time.
    """
    import pymssql

    kwargs.setdefault("charset", "UTF-8")

    def _try(version: str) -> Any:
        return pymssql.connect(tds_version=version, **kwargs)

    key = _cache_key(kwargs)

    pinned = tds_version
    if not pinned:
        with _negotiated_lock:
            pinned = _negotiated.get(key)
    if pinned:
        return _try(pinned), pinned

    last_error: Exception = RuntimeError("No TDS version could be negotiated")
    for version in (PREFERRED_TDS_VERSION, *FALLBACK_TDS_VERSIONS):
        try:
            conn = _try(version)
        except Exception as e:
            last_error = e
            if _is_fatal_error(e):
                raise
            logger.debug(
                "tds_version_rejected",
                server=kwargs.get("server"),
                tds_version=version,
                error=str(e)[:200],
            )
            continue

        with _negotiated_lock:
            _negotiated[key] = version
        if version != PREFERRED_TDS_VERSION:
            logger.warning(
                "tds_version_downgraded",
                server=kwargs.get("server"),
                tds_version=version,
                detail=(
                    "Server rejected TDS 7.4; text in non-Latin-1 code pages may "
                    "decode incorrectly on TDS 7.0."
                ),
            )
        return conn, version

    raise last_error
