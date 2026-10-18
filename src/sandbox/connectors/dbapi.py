"""
DB-API Connector

Base for the engines whose Python driver is a synchronous DB-API 2.0 module
(or can be given a cursor that looks like one). Everything the async
``BaseConnector`` interface asks for is done here, on a worker thread; an
engine's own connector says how to open a connection and how to read its
catalog.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncGenerator

from sandbox.connectors.base import BaseConnector, QueryResult
from sandbox.connectors.host_policy import vet_destination
from sandbox.connectors.tls import (
    VERIFYING_SSL_MODES,
    is_pem,
    resolve_ssl_mode,
    system_ca_file,
)
from sandbox.core.exceptions import ConnectionError, SQLExecutionError
from sandbox.core.logging import get_logger

logger = get_logger(__name__)

_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="dbapi")

# :name, but not the second colon of a ::cast.
_NAMED_PARAM = re.compile(r"(?<!:):(\w+)")


class DBAPIConnector(BaseConnector[Any]):
    """
    Connector over a synchronous DB-API 2.0 driver.

    A subclass gives ``_open`` (dial and return a driver connection) and the
    two catalog queries. The driver is imported inside ``_open`` so a sandbox
    image without it still starts; the factory reports the type as missing its
    driver from ``driver_modules``.
    """

    # How errors name the engine ("Trino", "Oracle").
    label: str = ""
    # Modules the connector imports to dial; the factory checks they exist.
    driver_modules: tuple[str, ...] = ()
    # The driver's positional placeholder: "?" (qmark) or "%s" (format).
    placeholder: str = "?"
    ping_sql: str = "SELECT 1"

    # ------------------------------------------------------------------
    # What an engine's connector provides
    # ------------------------------------------------------------------

    def _open(self) -> Any:
        """Dial and return a driver connection. Runs on a worker thread."""
        raise NotImplementedError

    def _host(self) -> str:
        """The host this connection dials, for the destination check."""
        return self.config.host

    def _default_schema(self) -> str | None:
        """The schema the catalog lists when the connection names none."""
        return None

    def _entries_query(self, schema: str | None) -> tuple[str, tuple[Any, ...]]:
        """SQL returning ``(name, kind)`` for the tables and views of a schema."""
        raise NotImplementedError

    def _columns_query(
        self, schema: str | None, table: str | None
    ) -> tuple[str, tuple[Any, ...]]:
        """SQL returning ``(table, column, type, nullable, default, max_length,
        precision, scale)`` in table then column order, for one table or, when
        ``table`` is None, for every table of the schema. Trailing fields an
        engine's catalog does not have may be left off."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helpers for subclasses
    # ------------------------------------------------------------------

    def _param(self, name: str, default: Any = None) -> Any:
        """A type-specific field of the connection form (``extra_params``)."""
        value = (self.config.extra_params or {}).get(name)
        return default if value in (None, "") else value

    def _ssl_mode(self) -> str:
        return resolve_ssl_mode(self.config)

    def _ca_file(self) -> str | None:
        """The connection's CA certificate as a file, for drivers that only
        take a path. PEM text is written once per certificate."""
        ca_cert = self.config.ssl_ca_cert
        if not ca_cert:
            return None
        if not is_pem(ca_cert):
            return ca_cert
        digest = hashlib.sha256(ca_cert.encode()).hexdigest()[:24]
        path = os.path.join(tempfile.gettempdir(), f"sandbox-ca-{digest}.pem")
        if not os.path.exists(path):
            fd, partial = tempfile.mkstemp(dir=tempfile.gettempdir(), suffix=".pem")
            with os.fdopen(fd, "w") as handle:
                handle.write(ca_cert)
            os.replace(partial, path)
        return path

    def _trust_store(self, mode: str) -> str:
        """The CA file a verifying mode checks against, or a refusal."""
        trust_store = self._ca_file() or system_ca_file()
        if not trust_store:
            raise self._refuse(
                f"SSL mode '{mode}' needs to verify the server certificate, but no CA "
                "certificate was given and this sandbox has no system trust store. "
                "Add the CA certificate to the connection. Not connecting."
            )
        return trust_store

    def _http_tls(self, default: str = "disable") -> tuple[str, bool | str]:
        """``(scheme, verify)`` for a driver that speaks HTTP.

        HTTP has no "TLS if offered", so ``allow``/``prefer`` are refused. A
        client that verifies checks the host name too, so ``verify-ca`` runs
        as ``verify-full``.
        """
        cfg = self.config
        mode = self._ssl_mode() if (cfg.ssl_mode or cfg.ssl_enabled) else default
        if mode == "disable":
            return "http", False
        if mode in ("allow", "prefer"):
            raise self._refuse(
                f"SSL mode '{mode}' is not available for {self.label}: the link is "
                "either HTTPS or it is not. Use 'disable' or 'require'. Not connecting."
            )
        if mode in VERIFYING_SSL_MODES:
            return "https", self._trust_store(mode)
        return "https", False

    def _refuse(self, message: str) -> ConnectionError:
        return ConnectionError(
            message, connection_id=self.connection_id, db_type=self.db_type
        )

    def _require(self, value: Any, field: str) -> Any:
        if value in (None, ""):
            raise self._refuse(f"{self.label} needs '{field}'. Not connecting.")
        return value

    # ------------------------------------------------------------------
    # BaseConnector
    # ------------------------------------------------------------------

    async def connect(self) -> Any:
        cfg = self.config
        # Where this may point is decided in connectors/host_policy.py. The
        # driver dials the host by name and exposes no socket to check.
        await vet_destination(cfg.model_copy(update={"host": self._host()}))

        def _connect() -> Any:
            try:
                return self._open()
            except ConnectionError:
                raise
            except Exception as e:
                raise ConnectionError(
                    f"Failed to connect to {self.label}: {e}",
                    connection_id=cfg.id,
                    db_type=self.db_type,
                    cause=e,
                )

        conn = await _run(_connect)
        self._logger.debug(
            "connection_created",
            connection_id=self.connection_id,
            host=self._host(),
            database=cfg.database,
        )
        return conn

    async def close_connection(self, conn: Any) -> None:
        try:
            await _run(conn.close)
        except Exception as e:
            self._logger.warning(
                "connection_close_error",
                connection_id=self.connection_id,
                error=str(e),
            )

    def _run_query(
        self, conn: Any, query: str, parameters: dict[str, Any] | None
    ) -> Any:
        cursor = conn.cursor()
        if parameters:
            converted, args = self._convert_parameters(query, parameters)
            cursor.execute(converted, args)
        else:
            cursor.execute(query)
        return cursor

    async def execute(
        self,
        conn: Any,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult:
        def _execute() -> QueryResult:
            try:
                cursor = self._run_query(conn, query, parameters)
                try:
                    if cursor.description:
                        columns = [desc[0] for desc in cursor.description]
                        column_types = [
                            str(getattr(desc[1], "name", None) or desc[1])
                            for desc in cursor.description
                        ]
                        rows = [tuple(r) for r in (cursor.fetchall() or [])]
                    else:
                        columns, column_types, rows = [], [], []
                    affected = getattr(cursor, "rowcount", -1)
                    return QueryResult(
                        columns=columns,
                        column_types=column_types,
                        rows=rows,
                        row_count=len(rows),
                        affected_rows=affected if isinstance(affected, int) and affected >= 0 else 0,
                    )
                finally:
                    _close_quietly(cursor)
            except Exception as e:
                raise SQLExecutionError(
                    f"Query execution failed: {e}",
                    query=query,
                    cause=e,
                )

        return await _run(_execute)

    async def execute_streaming(
        self,
        conn: Any,
        query: str,
        parameters: dict[str, Any] | None = None,
        batch_size: int = 1000,
    ) -> AsyncGenerator[list[tuple[Any, ...]], None]:
        def _fetch_batch(cursor: Any) -> list[tuple[Any, ...]]:
            return [tuple(r) for r in cursor.fetchmany(batch_size)]

        cursor = None
        try:
            cursor = await _run(self._run_query, conn, query, parameters)
            while True:
                batch = await _run(_fetch_batch, cursor)
                if not batch:
                    break
                yield batch
        except Exception as e:
            raise SQLExecutionError(
                f"Streaming query failed: {e}",
                query=query,
                cause=e,
            )
        finally:
            if cursor is not None:
                await _run(_close_quietly, cursor)

    def _fetch(self, conn: Any, sql: str, args: Any) -> list[Any]:
        cursor = conn.cursor()
        try:
            if args:
                cursor.execute(sql, args)
            else:
                cursor.execute(sql)
            return list(cursor.fetchall() or [])
        finally:
            _close_quietly(cursor)

    async def get_tables(self, conn: Any, schema: str | None = None) -> list[str]:
        return [e["name"] for e in await self.get_table_entries(conn, schema=schema)]

    async def get_table_entries(
        self, conn: Any, schema: str | None = None
    ) -> list[dict[str, Any]]:
        sql, args = self._entries_query(self._schema(schema))

        def _entries() -> list[dict[str, Any]]:
            seen: dict[str, dict[str, Any]] = {}
            for row in self._fetch(conn, sql, args):
                seen.setdefault(row[0], {"name": row[0], "type": _kind(row[1])})
            return sorted(seen.values(), key=lambda e: str(e["name"]).lower())

        return await _run(_entries)

    async def get_columns(
        self, conn: Any, table: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        sql, args = self._columns_query(self._schema(schema), table)
        rows = await _run(self._fetch, conn, sql, args)
        return [_column_row(row[1:]) for row in rows]

    async def get_all_columns(
        self, conn: Any, schema: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Columns of every table and view of the schema in one query."""
        sql, args = self._columns_query(self._schema(schema), None)
        tables: dict[str, list[dict[str, Any]]] = {}
        for row in await _run(self._fetch, conn, sql, args):
            tables.setdefault(row[0], []).append(_column_row(row[1:]))
        return tables

    async def test_connection(self, conn: Any) -> bool:
        def _test() -> bool:
            try:
                self._fetch(conn, self.ping_sql, ())
                return True
            except Exception:
                return False

        return await _run(_test)

    def _schema(self, schema: str | None) -> str | None:
        return schema or self.config.schema_name or self._default_schema()

    def _convert_parameters(
        self, query: str, parameters: dict[str, Any]
    ) -> tuple[str, tuple[Any, ...]]:
        """Named parameters (:name) to the driver's positional placeholder.

        Only the names that were passed are parameters; any other ``:word``
        (a time literal, a slice) is left as written.
        """
        args: list[Any] = []

        def _positional(match: re.Match[str]) -> str:
            if match.group(1) not in parameters:
                return match.group(0)
            args.append(parameters[match.group(1)])
            return self.placeholder

        if self.placeholder == "%s":
            # A driver that formats with % reads every other % as its own.
            query = query.replace("%", "%%")
        return _NAMED_PARAM.sub(_positional, query), tuple(args)


class InformationSchemaMixin:
    """Catalog queries for engines with a standard ``information_schema``.

    Only the columns every implementation has are read. ``_catalog_prefix``
    qualifies the schema for engines where it lives under a catalog or a
    dataset (``mycatalog.information_schema``).
    """

    def _catalog_prefix(self, schema: str | None) -> str:
        return ""

    def _entries_query(self, schema: str | None) -> tuple[str, tuple[Any, ...]]:
        p = self.placeholder  # type: ignore[attr-defined]
        return (
            "SELECT table_name, table_type "
            f"FROM {self._catalog_prefix(schema)}information_schema.tables "
            f"WHERE table_schema = {p}",
            (schema,),
        )

    def _columns_query(
        self, schema: str | None, table: str | None
    ) -> tuple[str, tuple[Any, ...]]:
        p = self.placeholder  # type: ignore[attr-defined]
        sql = (
            "SELECT table_name, column_name, data_type, is_nullable, column_default "
            f"FROM {self._catalog_prefix(schema)}information_schema.columns "
            f"WHERE table_schema = {p}"
        )
        args: tuple[Any, ...] = (schema,)
        if table is not None:
            sql += f" AND table_name = {p}"
            args += (table,)
        return sql + " ORDER BY table_name, ordinal_position", args


class SimpleCursor:
    """The part of a DB-API cursor this module uses, for engines reached
    through an API instead of a driver. A subclass implements ``_run``."""

    def __init__(self) -> None:
        self.description: list[tuple[Any, ...]] | None = None
        self.rowcount = -1
        self._rows: list[tuple[Any, ...]] = []
        self._position = 0

    def _run(self, sql: str) -> tuple[list[tuple[str, str]], list[tuple[Any, ...]]]:
        """Run ``sql``; return ``([(column, type)], rows)``."""
        raise NotImplementedError

    def execute(self, operation: str, parameters: Any = None) -> None:
        if parameters:
            operation = _inline_parameters(operation, parameters)
        columns, rows = self._run(operation)
        self.description = (
            [(name, type_name, None, None, None, None, None) for name, type_name in columns]
            if columns
            else None
        )
        self._rows = rows
        self._position = 0

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows = self._rows[self._position:]
        self._position = len(self._rows)
        return rows

    def fetchmany(self, size: int = 1000) -> list[tuple[Any, ...]]:
        rows = self._rows[self._position:self._position + size]
        self._position += len(rows)
        return rows

    def close(self) -> None:
        self._rows = []


def sql_literal(value: Any) -> str:
    """A value as an ANSI SQL literal, for APIs that take no parameters."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _inline_parameters(operation: str, parameters: Any) -> str:
    values = iter(parameters)
    return re.sub(r"\?", lambda _m: sql_literal(next(values)), operation)


def _close_quietly(cursor: Any) -> None:
    try:
        cursor.close()
    except Exception:
        pass


async def _run(fn: Any, *args: Any) -> Any:
    return await asyncio.get_running_loop().run_in_executor(_executor, fn, *args)


def _kind(value: Any) -> str:
    """A catalog's table type as TABLE or VIEW."""
    return "VIEW" if "VIEW" in str(value or "").upper() else "TABLE"


def _nullable(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().upper() in ("YES", "Y", "TRUE", "1", "NULLABLE")
    return bool(value) if value is not None else True


def _column_row(row: Any) -> dict[str, Any]:
    """(column, type, nullable, default[, max_length, precision, scale])"""
    row = tuple(row) + (None,) * (7 - len(row))
    return {
        "name": row[0],
        "type": str(row[1]) if row[1] is not None else "",
        "nullable": _nullable(row[2]),
        "default": row[3],
        "max_length": row[4],
        "precision": row[5],
        "scale": row[6],
    }
