"""
MSSQL Database Connector

Provides async SQL Server connectivity using pymssql wrapped in asyncio executor.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncGenerator

from sandbox.connectors.base import BaseConnector, QueryResult
from sandbox.connectors.mssql_tds import (
    connect_mssql,
    detect_codepage,
    needs_repair,
    repair_row,
    repair_text,
)
from sandbox.core.exceptions import ConnectionError, SQLExecutionError
from sandbox.core.logging import get_logger

logger = get_logger(__name__)

# Fallback pool for work not tied to one physical connection.
_executor = ThreadPoolExecutor(max_workers=10)

# Every open pymssql connection gets its own single worker thread, keyed by
# id(conn).
#
# FreeTDS aborts the *whole process* — "tds_free_connection: Assertion
# `conn->in_net_tds == NULL' failed" — when a connection is freed while another
# thread is inside a net read on it. A shared pool produced exactly that: the
# schema full-sync route wraps each connection in asyncio.wait_for, and when the
# deadline fired, every in-flight `async with get_connection()` unwound and
# submitted conn.close() to *some other* worker thread while the query thread was
# still reading that same socket. One abort() took the sandbox down for every
# space (the uvicorn worker died; its parent kept the listening socket, so all
# later requests hung until the caller's own timeout).
#
# Pinning a connection to a single thread makes close() strictly ordered behind
# whatever is already running on it, so a cancelled query can never free a socket
# out from under FreeTDS.
_conn_executors: dict[int, ThreadPoolExecutor] = {}
_conn_executors_lock = threading.Lock()


def _register_executor(conn: Any, ex: ThreadPoolExecutor) -> None:
    """Pin ``conn`` to ``ex``, retiring any stale mapping for a reused id()."""
    with _conn_executors_lock:
        stale = _conn_executors.get(id(conn))
        _conn_executors[id(conn)] = ex
    if stale is not None and stale is not ex:
        stale.shutdown(wait=False)


def _executor_for(conn: Any) -> ThreadPoolExecutor:
    """The thread that owns ``conn``; the shared pool if it isn't pinned."""
    with _conn_executors_lock:
        return _conn_executors.get(id(conn), _executor)


def _pop_executor(conn: Any) -> ThreadPoolExecutor | None:
    with _conn_executors_lock:
        return _conn_executors.pop(id(conn), None)


def _retire(conn: Any, ex: ThreadPoolExecutor | None) -> None:
    """Queue conn.close() on its own thread and let that thread exit after.

    Deliberately fire-and-forget: it must stay safe to call from a coroutine
    that is already being cancelled, where any `await` would re-raise before the
    close could be issued. Ordering on the connection's single thread is what
    guarantees the close lands after the in-flight query rather than during it.
    """
    def _close() -> None:
        try:
            conn.close()
        except Exception:
            pass

    if ex is None:
        _executor.submit(_close)
        return
    try:
        ex.submit(_close)
    except RuntimeError:
        # Executor already shut down — the connection is gone with it.
        return
    ex.shutdown(wait=False)


class MSSQLConnector(BaseConnector[Any]):
    """
    SQL Server connector using pymssql.

    pymssql is synchronous, so all operations are offloaded to a thread
    executor to remain compatible with the async BaseConnector interface.
    """

    # Code page of the connected database, resolved on connect. 1252 means
    # FreeTDS decoded correctly and result rows are passed through untouched.
    _codepage: int = 1252

    async def connect(self) -> Any:
        """Create a new SQL Server connection."""
        cfg = self.config

        def _connect() -> Any:
            import pymssql
            try:
                # The TDS version is negotiated (7.4 first) rather than pinned to
                # 7.0: only 7.1+ carries per-column collation, and without it
                # FreeTDS decodes CP1254/CP1250/... varchar data as ISO-8859-1
                # ('Ş' -> 'Þ') no matter what the client charset says.
                conn, negotiated = connect_mssql(
                    tds_version=cfg.extra_params.get("tds_version"),
                    server=cfg.host,
                    port=str(cfg.port),
                    database=cfg.database,
                    user=cfg.username,
                    password=cfg.password.get_secret_value(),
                    login_timeout=int(cfg.connection_timeout),
                    # Driver-level query timeout. Without it a single blocked
                    # query (lock wait, linked server, unresponsive host) pins
                    # its thread forever; the async side can only stop *waiting*
                    # for a thread, never stop the thread itself.
                    timeout=max(1, int(cfg.query_timeout)),
                    as_dict=False,
                    charset="UTF-8",
                )
                # Remember it on the in-memory config so reconnects skip the probe.
                cfg.extra_params["tds_version"] = negotiated
                return conn
            except pymssql.OperationalError as e:
                raise ConnectionError(
                    f"Failed to connect to SQL Server: {e}",
                    connection_id=cfg.id,
                    db_type="mssql",
                    cause=e,
                )
            except Exception as e:
                raise ConnectionError(
                    f"Failed to connect to SQL Server: {e}",
                    connection_id=cfg.id,
                    db_type="mssql",
                    cause=e,
                )

        loop = asyncio.get_event_loop()

        # Open on the thread that will own this connection for its whole life,
        # so no FreeTDS socket is ever touched by two threads (see _conn_executors).
        ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mssql-conn")
        try:
            conn = await loop.run_in_executor(ex, _connect)
        except BaseException:
            ex.shutdown(wait=False)
            raise

        _register_executor(conn, ex)

        try:
            # FreeTDS decodes every varchar with the server's default code page, so
            # a database on a different one (e.g. Turkish_CI_AS under a CP1252
            # server) needs its rows re-decoded. Resolved once per connection.
            self._codepage = await loop.run_in_executor(ex, detect_codepage, conn)
        except BaseException:
            # Includes CancelledError: nobody will receive this connection, so
            # retire it here rather than leak the socket and its thread.
            _retire(conn, _pop_executor(conn))
            raise

        self._logger.info(
            "connection_created",
            connection_id=self.connection_id,
            host=cfg.host,
            database=cfg.database,
            tds_version=cfg.extra_params.get("tds_version"),
            codepage=self._codepage,
        )

        return conn

    async def close_connection(self, conn: Any) -> None:
        """Close a SQL Server connection.

        Never awaits. get_connection() calls this from a `finally` that often
        runs while the surrounding task is being cancelled, and an `await` there
        raises CancelledError before the close is even issued — which is how
        connections used to be abandoned mid-query and freed by the wrong thread.
        """
        _retire(conn, _pop_executor(conn))

    async def execute(
        self,
        conn: Any,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a query and return results."""

        def _execute() -> QueryResult:
            try:
                cursor = conn.cursor()
                if parameters:
                    query_converted, args = _convert_parameters(query, parameters)
                    cursor.execute(query_converted, args)
                else:
                    cursor.execute(query)

                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    column_types = [
                        _pymssql_type_name(desc[1]) for desc in cursor.description
                    ]
                    rows = cursor.fetchall() or []
                    codepage = self._codepage
                    if needs_repair(codepage):
                        rows = [repair_row(tuple(r), codepage) for r in rows]
                        columns = [repair_text(c, codepage) for c in columns]
                    else:
                        rows = [tuple(r) for r in rows]
                else:
                    columns = []
                    column_types = []
                    rows = []

                return QueryResult(
                    columns=columns,
                    column_types=column_types,
                    rows=rows,
                    row_count=len(rows),
                    affected_rows=cursor.rowcount if cursor.rowcount >= 0 else 0,
                )
            except Exception as e:
                raise SQLExecutionError(
                    f"Query execution failed: {e}",
                    query=query,
                    cause=e,
                )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor_for(conn), _execute)

    async def execute_streaming(
        self,
        conn: Any,
        query: str,
        parameters: dict[str, Any] | None = None,
        batch_size: int = 1000,
    ) -> AsyncGenerator[list[tuple[Any, ...]], None]:
        """Execute a query and stream results in batches."""

        def _fetch_batch(cursor: Any) -> list[tuple[Any, ...]]:
            rows = cursor.fetchmany(batch_size)
            codepage = self._codepage
            if needs_repair(codepage):
                return [repair_row(tuple(r), codepage) for r in rows]
            return [tuple(r) for r in rows]

        def _prepare(q: str, params: dict[str, Any] | None) -> Any:
            cursor = conn.cursor()
            if params:
                q_converted, args = _convert_parameters(q, params)
                cursor.execute(q_converted, args)
            else:
                cursor.execute(q)
            return cursor

        loop = asyncio.get_event_loop()
        try:
            cursor = await loop.run_in_executor(_executor_for(conn), _prepare, query, parameters)
            while True:
                batch = await loop.run_in_executor(_executor_for(conn), _fetch_batch, cursor)
                if not batch:
                    break
                yield batch
        except Exception as e:
            raise SQLExecutionError(
                f"Streaming query failed: {e}",
                query=query,
                cause=e,
            )

    async def get_tables(self, conn: Any, schema: str | None = None) -> list[str]:
        """Get list of tables in the database, defaulting schema to 'dbo'."""
        schema = schema or self.config.schema_name or "dbo"

        def _get_tables() -> list[str]:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_TYPE IN ('BASE TABLE', 'VIEW')
                ORDER BY TABLE_NAME
                """,
                (schema,),
            )
            return [row[0] for row in cursor.fetchall()]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor_for(conn), _get_tables)

    async def get_columns(
        self, conn: Any, table: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        """Get column information for a table."""
        schema = schema or self.config.schema_name or "dbo"

        def _get_columns() -> list[dict[str, Any]]:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    c.COLUMN_NAME,
                    c.DATA_TYPE,
                    c.IS_NULLABLE,
                    c.COLUMN_DEFAULT,
                    c.CHARACTER_MAXIMUM_LENGTH,
                    c.NUMERIC_PRECISION,
                    c.NUMERIC_SCALE,
                    CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS IS_PRIMARY_KEY
                FROM INFORMATION_SCHEMA.COLUMNS c
                LEFT JOIN (
                    SELECT kcu.COLUMN_NAME
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                        ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                        AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                    WHERE tc.TABLE_SCHEMA = %s
                      AND tc.TABLE_NAME = %s
                      AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                ) pk ON pk.COLUMN_NAME = c.COLUMN_NAME
                WHERE c.TABLE_SCHEMA = %s
                  AND c.TABLE_NAME = %s
                ORDER BY c.ORDINAL_POSITION
                """,
                (schema, table, schema, table),
            )
            return [
                {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2] == "YES",
                    "default": row[3],
                    "max_length": row[4],
                    "precision": row[5],
                    "scale": row[6],
                    "is_primary_key": bool(row[7]),
                }
                for row in cursor.fetchall()
            ]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor_for(conn), _get_columns)

    async def get_all_columns(
        self, conn: Any, schema: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Batch-fetch columns for EVERY table in the schema in one query.

        Returns ``{table_name: [columns]}``. The full-sync route takes a much
        cheaper path when a connector offers this (see rest_api.full_sync_schema):
        without it, every table costs its own connection plus its own
        INFORMATION_SCHEMA round trip. On a 286-table CRM database that measured
        51s of fan-out versus 1.5s here — and the fan-out is what pushed schema
        sync past the route's deadline in the first place.

        Key/constraint flags come from the sys.* catalog views rather than
        INFORMATION_SCHEMA.KEY_COLUMN_USAGE: the latter is re-scanned per table
        and dominates the per-table query's cost (1.8s median under concurrency).
        """
        schema = schema or self.config.schema_name or "dbo"

        def _get_all_columns() -> dict[str, list[dict[str, Any]]]:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    c.TABLE_NAME,
                    c.COLUMN_NAME,
                    c.DATA_TYPE,
                    c.IS_NULLABLE,
                    c.COLUMN_DEFAULT,
                    c.CHARACTER_MAXIMUM_LENGTH,
                    c.NUMERIC_PRECISION,
                    c.NUMERIC_SCALE,
                    CASE WHEN pk.column_name IS NOT NULL THEN 1 ELSE 0 END,
                    CASE WHEN uq.column_name IS NOT NULL THEN 1 ELSE 0 END,
                    fk.ref_schema,
                    fk.ref_table,
                    fk.ref_column
                FROM INFORMATION_SCHEMA.COLUMNS c
                LEFT JOIN (
                    SELECT DISTINCT s.name AS schema_name, t.name AS table_name,
                           col.name AS column_name
                    FROM sys.key_constraints kc
                    JOIN sys.tables t ON t.object_id = kc.parent_object_id
                    JOIN sys.schemas s ON s.schema_id = t.schema_id
                    JOIN sys.index_columns ic
                      ON ic.object_id = kc.parent_object_id
                     AND ic.index_id = kc.unique_index_id
                    JOIN sys.columns col
                      ON col.object_id = ic.object_id AND col.column_id = ic.column_id
                    WHERE kc.type = 'PK'
                ) pk ON pk.schema_name = c.TABLE_SCHEMA
                    AND pk.table_name = c.TABLE_NAME
                    AND pk.column_name = c.COLUMN_NAME
                LEFT JOIN (
                    SELECT DISTINCT s.name AS schema_name, t.name AS table_name,
                           col.name AS column_name
                    FROM sys.key_constraints kc
                    JOIN sys.tables t ON t.object_id = kc.parent_object_id
                    JOIN sys.schemas s ON s.schema_id = t.schema_id
                    JOIN sys.index_columns ic
                      ON ic.object_id = kc.parent_object_id
                     AND ic.index_id = kc.unique_index_id
                    JOIN sys.columns col
                      ON col.object_id = ic.object_id AND col.column_id = ic.column_id
                    WHERE kc.type = 'UQ'
                ) uq ON uq.schema_name = c.TABLE_SCHEMA
                    AND uq.table_name = c.TABLE_NAME
                    AND uq.column_name = c.COLUMN_NAME
                LEFT JOIN (
                    SELECT s.name AS schema_name, t.name AS table_name,
                           pc.name AS column_name,
                           rs.name AS ref_schema, rt.name AS ref_table,
                           rc.name AS ref_column,
                           ROW_NUMBER() OVER (
                               PARTITION BY s.name, t.name, pc.name
                               ORDER BY rt.name, rc.name
                           ) AS rn
                    FROM sys.foreign_key_columns fkc
                    JOIN sys.tables t ON t.object_id = fkc.parent_object_id
                    JOIN sys.schemas s ON s.schema_id = t.schema_id
                    JOIN sys.columns pc
                      ON pc.object_id = fkc.parent_object_id
                     AND pc.column_id = fkc.parent_column_id
                    JOIN sys.tables rt ON rt.object_id = fkc.referenced_object_id
                    JOIN sys.schemas rs ON rs.schema_id = rt.schema_id
                    JOIN sys.columns rc
                      ON rc.object_id = fkc.referenced_object_id
                     AND rc.column_id = fkc.referenced_column_id
                ) fk ON fk.schema_name = c.TABLE_SCHEMA
                    AND fk.table_name = c.TABLE_NAME
                    AND fk.column_name = c.COLUMN_NAME
                    AND fk.rn = 1
                WHERE c.TABLE_SCHEMA = %s
                ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
                """,
                (schema,),
            )

            tables: dict[str, list[dict[str, Any]]] = {}
            for row in cursor.fetchall():
                table_name = row[0]
                ref_table = row[11]
                tables.setdefault(table_name, []).append({
                    "name": row[1],
                    "type": row[2],
                    "nullable": row[3] == "YES",
                    "default": row[4],
                    "max_length": row[5],
                    "precision": row[6],
                    "scale": row[7],
                    "is_primary_key": bool(row[8]),
                    "is_unique": bool(row[9]),
                    "is_foreign_key": ref_table is not None,
                    "foreign_table": (
                        f"{row[10]}.{ref_table}.{row[12]}" if ref_table else None
                    ),
                })
            return tables

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor_for(conn), _get_all_columns)

    async def test_connection(self, conn: Any) -> bool:
        """Test if connection is valid."""
        def _test() -> bool:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                return True
            except Exception:
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor_for(conn), _test)


def _convert_parameters(
    query: str, parameters: dict[str, Any]
) -> tuple[str, tuple[Any, ...]]:
    """Convert named parameters (:name) to pymssql positional (%s)."""
    import re

    pattern = r":(\w+)"
    matches = re.findall(pattern, query)
    args = [parameters.get(m) for m in matches]
    converted_query = re.sub(pattern, "%s", query)
    return converted_query, tuple(args)


def _pymssql_type_name(type_code: Any) -> str:
    """Map a pymssql DB-API type object or code to a human-readable name."""
    import pymssql
    for attr in ("STRING", "NUMBER", "DATETIME", "ROWID", "BINARY", "DECIMAL"):
        val = getattr(pymssql, attr, None)
        if val is None:
            continue
        try:
            if type_code == val:
                return attr
        except Exception:
            pass
    return str(type_code)
