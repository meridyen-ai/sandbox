"""
MSSQL Database Connector

Provides async SQL Server connectivity using pymssql wrapped in asyncio executor.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from datetime import time as dt_time
from decimal import Decimal
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
from sandbox.execution.virtual_objects.models import (
    ExpansionPlan,
    MaterializeStep,
    VirtualColumn,
    VirtualObject,
)

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
                return self._read_result(cursor)
            except Exception as e:
                raise SQLExecutionError(
                    f"Query execution failed: {e}",
                    query=query,
                    cause=e,
                )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor_for(conn), _execute)

    def _repair(self, rows: list[Any]) -> list[tuple[Any, ...]]:
        codepage = self._codepage
        if needs_repair(codepage):
            return [repair_row(tuple(r), codepage) for r in rows]
        return [tuple(r) for r in rows]

    def _read_result(self, cursor: Any) -> QueryResult:
        """Rows of the current result set, code-page repaired."""
        if cursor.description:
            columns = [desc[0] for desc in cursor.description]
            column_types = [_pymssql_type_name(desc[1]) for desc in cursor.description]
            rows = self._repair(cursor.fetchall() or [])
            if needs_repair(self._codepage):
                columns = [repair_text(c, self._codepage) for c in columns]
        else:
            columns, column_types, rows = [], [], []
        return QueryResult(
            columns=columns,
            column_types=column_types,
            rows=rows,
            row_count=len(rows),
            affected_rows=cursor.rowcount if cursor.rowcount >= 0 else 0,
        )

    # ------------------------------------------------------------------
    # Virtual objects: stored procedures as tables
    # ------------------------------------------------------------------

    async def execute_plan(
        self,
        conn: Any,
        plan: ExpansionPlan,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Fill a session temp table per procedure, then run the query.

        Everything — creating, filling, querying and dropping the temp tables —
        happens inside ONE function on the connection's own thread. Temp tables
        are session-scoped, and running cleanup in the same function guarantees
        it lands after the query even when the async side has already given up
        waiting (timeout/cancel): the thread is never interrupted mid-batch.

        tempdb needs no permission on the user database, which is the point:
        this works for a login that may only SELECT and EXECUTE.
        """
        if not plan.steps:
            return await self.execute(conn, plan.sql, parameters)

        def _run() -> QueryResult:
            cursor = conn.cursor()
            created: list[str] = []
            try:
                for step in plan.steps:
                    temp = _temp_name(step.temp_name)
                    columns = step.obj.columns
                    cursor.execute(_drop_temp_sql(temp))
                    cursor.execute(f"CREATE TABLE {temp} ({_temp_table_ddl(columns)})")
                    created.append(temp)
                    if step.cached_rows is not None:
                        _bulk_insert(cursor, temp, columns, step.cached_rows)
                    elif step.mode == "insert_exec":
                        try:
                            cursor.execute(f"INSERT INTO {temp} {_exec_sql(step.obj, step.params)}")
                        except Exception as e:
                            if _error_number(e) not in _INSERT_EXEC_UNSUPPORTED:
                                raise
                            # The procedure cannot run inside INSERT…EXEC (it
                            # nests one itself, or rolls back). Fetch instead.
                            logger.info(
                                "virtual_object_insert_exec_fallback",
                                object=step.obj.name,
                                error_number=_error_number(e),
                            )
                            cursor.execute(f"DELETE FROM {temp}")
                            self._fill_client_side(cursor, step, temp)
                    else:
                        self._fill_client_side(cursor, step, temp)

                if parameters:
                    query_converted, args = _convert_parameters(plan.sql, parameters)
                    cursor.execute(query_converted, args)
                else:
                    cursor.execute(plan.sql)
                return self._read_result(cursor)
            except Exception as e:
                raise SQLExecutionError(
                    f"Query execution failed: {e}", query=plan.sql, cause=e
                )
            finally:
                for temp in created:
                    try:
                        cursor.execute(_drop_temp_sql(temp))
                    except Exception:
                        pass

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor_for(conn), _run)

    def _fill_client_side(self, cursor: Any, step: MaterializeStep, temp: str) -> None:
        rows = self._fetch_procedure_rows(
            cursor, step.obj, step.params, step.obj.result_set_index, CLIENT_MAX_ROWS
        ).rows
        if rows and len(rows[0]) != len(step.obj.columns):
            raise SQLExecutionError(
                f"'{step.obj.name}' now returns {len(rows[0])} columns instead of "
                f"{len(step.obj.columns)}; refresh its definition"
            )
        step.fetched_rows = rows
        _bulk_insert(cursor, temp, step.obj.columns, rows)

    def _fetch_procedure_rows(
        self,
        cursor: Any,
        obj: VirtualObject,
        params: list[tuple[str, Any]],
        result_set_index: int,
        max_rows: int,
    ) -> QueryResult:
        """EXEC the procedure and read result set ``result_set_index``.

        Strings are code-page repaired here, so what is re-inserted into the
        temp table (or cached) is already correct Unicode.
        """
        cursor.execute(_exec_sql(obj, params))
        found: QueryResult | None = None
        index = 0
        while True:
            if cursor.description:
                if index == result_set_index and found is None:
                    raw = cursor.fetchmany(max_rows + 1) or []
                    if len(raw) > max_rows:
                        raise SQLExecutionError(
                            f"'{obj.name}' returned more than {max_rows} rows"
                        )
                    columns = [d[0] for d in cursor.description]
                    if needs_repair(self._codepage):
                        columns = [repair_text(c, self._codepage) for c in columns]
                    rows = self._repair(raw)
                    found = QueryResult(
                        columns=columns,
                        column_types=[_pymssql_type_name(d[1]) for d in cursor.description],
                        rows=rows,
                        row_count=len(rows),
                    )
                else:
                    cursor.fetchall()
                index += 1
            if not cursor.nextset():
                break
        if found is None:
            raise SQLExecutionError(
                f"'{obj.name}' returned {index} result set(s); "
                f"result set #{result_set_index + 1} does not exist"
            )
        found.result_set_count = index
        return found

    async def exec_procedure(
        self,
        conn: Any,
        obj: VirtualObject,
        params: list[tuple[str, Any]],
        max_rows: int,
    ) -> QueryResult:
        """Run a procedure directly and return one result set (preview/describe)."""

        def _run() -> QueryResult:
            cursor = conn.cursor()
            try:
                return self._fetch_procedure_rows(
                    cursor, obj, params, obj.result_set_index, max_rows
                )
            except SQLExecutionError:
                raise
            except Exception as e:
                raise SQLExecutionError(f"Procedure execution failed: {e}", cause=e)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor_for(conn), _run)

    async def probe_insert_exec(
        self, conn: Any, obj: VirtualObject, params: list[tuple[str, Any]]
    ) -> tuple[bool, str | None]:
        """Can this procedure be materialized with INSERT…EXEC?

        (True, None) if it can; (False, None) if SQL Server refuses INSERT…EXEC
        for it (nesting, rollback) so client-side fetching must be used;
        (False, message) for any other failure.
        """

        def _run() -> tuple[bool, str | None]:
            cursor = conn.cursor()
            temp = "#mv_probe_1"
            try:
                cursor.execute(_drop_temp_sql(temp))
                cursor.execute(f"CREATE TABLE {temp} ({_temp_table_ddl(obj.columns)})")
                cursor.execute(f"INSERT INTO {temp} {_exec_sql(obj, params)}")
                return True, None
            except Exception as e:
                if _error_number(e) in _INSERT_EXEC_UNSUPPORTED:
                    return False, None
                return False, str(e)
            finally:
                try:
                    cursor.execute(_drop_temp_sql(temp))
                except Exception:
                    pass

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor_for(conn), _run)

    async def describe_sql(self, conn: Any, sql: str) -> list[dict[str, Any]] | None:
        def _run() -> list[dict[str, Any]] | None:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT name, system_type_name, is_nullable, error_message
                FROM sys.dm_exec_describe_first_result_set(%s, NULL, 0)
                ORDER BY column_ordinal
                """,
                (sql,),
            )
            return _described(cursor.fetchall())

        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(_executor_for(conn), _run)
        except Exception:
            return None

    async def describe_procedure(
        self, conn: Any, schema: str, name: str
    ) -> list[dict[str, Any]] | None:
        """First result set of a procedure from metadata, without running it.

        None when SQL Server cannot tell statically — typically a procedure
        that builds its result from a #temp table or dynamic SQL.
        """

        def _run() -> list[dict[str, Any]] | None:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT name, system_type_name, is_nullable, error_message
                FROM sys.dm_exec_describe_first_result_set_for_object(OBJECT_ID(%s), 0)
                ORDER BY column_ordinal
                """,
                (_quote_ident(schema) + "." + _quote_ident(name),),
            )
            return _described(cursor.fetchall())

        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(_executor_for(conn), _run)
        except Exception:
            return None

    async def list_routines(
        self, conn: Any, schema: str | None = None, search: str | None = None
    ) -> list[dict[str, Any]]:
        """Procedures the login may EXECUTE, with their parameters."""

        def _run() -> list[dict[str, Any]]:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT s.name, p.name, prm.name, TYPE_NAME(prm.user_type_id),
                       prm.max_length, prm.precision, prm.scale,
                       prm.is_output, prm.has_default_value, prm.parameter_id
                FROM sys.procedures p
                JOIN sys.schemas s ON s.schema_id = p.schema_id
                LEFT JOIN sys.parameters prm
                  ON prm.object_id = p.object_id AND prm.parameter_id > 0
                WHERE p.is_ms_shipped = 0
                  AND (%s IS NULL OR s.name = %s)
                  AND (%s IS NULL OR p.name LIKE %s)
                  AND HAS_PERMS_BY_NAME(
                        QUOTENAME(s.name) + '.' + QUOTENAME(p.name), 'OBJECT', 'EXECUTE'
                      ) = 1
                ORDER BY s.name, p.name, prm.parameter_id
                """,
                (schema, schema, search, f"%{search}%" if search else None),
            )
            routines: dict[tuple[str, str], dict[str, Any]] = {}
            for row in cursor.fetchall():
                key = (row[0], row[1])
                r = routines.setdefault(key, {
                    "schema": row[0],
                    "name": row[1],
                    "signature": None,
                    "params": [],
                })
                if row[2]:
                    r["params"].append({
                        "name": row[2].lstrip("@"),
                        "sql_type": _mssql_type(row[3], row[4], row[5], row[6]),
                        "is_output": bool(row[7]),
                        # T-SQL procedures never report has_default_value
                        # reliably; the UI offers "omit" instead.
                        "has_default": bool(row[8]),
                    })
            return list(routines.values())[:ROUTINE_LIST_LIMIT]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor_for(conn), _run)

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

    async def get_table_entries(
        self, conn: Any, schema: str | None = None
    ) -> list[dict[str, Any]]:
        """Same set as get_tables, but carrying TABLE vs VIEW."""
        schema = schema or self.config.schema_name or "dbo"

        def _get_entries() -> list[dict[str, Any]]:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_TYPE IN ('BASE TABLE', 'VIEW')
                ORDER BY TABLE_NAME
                """,
                (schema,),
            )
            return [
                {
                    "name": row[0],
                    "type": "VIEW" if row[1] == "VIEW" else "TABLE",
                }
                for row in cursor.fetchall()
            ]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor_for(conn), _get_entries)

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


# SQL Server errors meaning "this procedure cannot run inside INSERT…EXEC":
# 8164 nested INSERT EXEC, 3915 ROLLBACK inside INSERT-EXEC, 556 schema of the
# target changed by the procedure, 213 the rows do not fit the table (typically
# a procedure that returns several result sets of different shapes). Client
# mode reads just the chosen result set, and reports a genuine shape change
# as "refresh its definition".
_INSERT_EXEC_UNSUPPORTED = {8164, 3915, 556, 213}

# Upper bound on rows fetched into the sandbox for client-side materialization.
CLIENT_MAX_ROWS = int(os.environ.get("SANDBOX_VO_CLIENT_MAX_ROWS", "200000"))
ROUTINE_LIST_LIMIT = 1000

_TEMP_NAME_RE = re.compile(r"^#mv_[0-9a-z]+_\d+$")
_STRING_TYPES = {"char", "varchar", "text", "nchar", "nvarchar", "ntext"}
_HIGH_PRECISION_TIME = {"datetime2", "datetimeoffset", "time"}


def _quote_ident(name: str) -> str:
    return "[" + str(name).replace("]", "]]") + "]"


def _temp_name(name: str) -> str:
    if not _TEMP_NAME_RE.match(name):
        raise SQLExecutionError("Invalid temp table name")
    return name


def _drop_temp_sql(temp: str) -> str:
    # OBJECT_ID guard rather than DROP TABLE IF EXISTS: works on SQL Server 2008+.
    return f"IF OBJECT_ID('tempdb..{temp}') IS NOT NULL DROP TABLE {temp}"


def _base_type(sql_type: str) -> str:
    return re.split(r"[\s(]", (sql_type or "").strip().lower(), maxsplit=1)[0]


def _temp_table_ddl(columns: list[VirtualColumn]) -> str:
    """Column list for the temp table a procedure is materialized into.

    String columns get COLLATE DATABASE_DEFAULT: temp tables otherwise take
    tempdb's (server) collation, which both corrupts text from a database on a
    different code page (Turkish 'Ş' → '?') and makes joins against the real
    tables fail with a collation conflict. rowversion can't be inserted into,
    so it lands as binary(8). Every column is NULL-able regardless of what the
    metadata claims.
    """
    from sandbox.execution.virtual_objects.validation import validate_sql_type

    parts = []
    for col in columns:
        sql_type = (col.sql_type or "nvarchar(max)").strip()
        validate_sql_type(sql_type, f"column '{col.name}'")
        base = _base_type(sql_type)
        if base in ("timestamp", "rowversion"):
            sql_type = "binary(8)"
        collate = " COLLATE DATABASE_DEFAULT" if base in _STRING_TYPES else ""
        parts.append(f"{_quote_ident(col.name)} {sql_type}{collate} NULL")
    return ", ".join(parts)


def _literal(value: Any, sql_type: str = "") -> str:
    """A T-SQL literal for ``value``.

    Rendered here instead of through pymssql's parameter quoting, which sends
    bytes as a character literal (no implicit conversion to varbinary) and
    dates as 'YYYY-MM-DD' (read as YYYY-DD-MM by datetime under some login
    languages). Strings only need their quotes doubled inside N'...'.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return "NULL" if value != value or value in (float("inf"), float("-inf")) else repr(value)
    if isinstance(value, Decimal):
        return "NULL" if not value.is_finite() else format(value, "f")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "0x" + bytes(value).hex()
    if isinstance(value, datetime):
        digits = 7 if _base_type(sql_type) in _HIGH_PRECISION_TIME else 3
        text = value.strftime("%Y-%m-%dT%H:%M:%S")
        if value.microsecond:
            text += "." + f"{value.microsecond:06d}{'0' * 7}"[:digits]
        if value.utcoffset() is not None and _base_type(sql_type) == "datetimeoffset":
            off = value.strftime("%z")
            text += f"{off[:3]}:{off[3:]}"
        return f"'{text}'"
    if isinstance(value, date):
        return f"'{value.strftime('%Y%m%d')}'"
    if isinstance(value, dt_time):
        return f"'{value.isoformat()}'"
    return "N'" + str(value).replace("'", "''") + "'"


def _exec_sql(obj: VirtualObject, params: list[tuple[str, Any]]) -> str:
    """``EXEC [schema].[proc] @a = <literal>, ...`` for a registered procedure."""
    from sandbox.execution.virtual_objects.validation import validate_routine_name

    validate_routine_name(obj.routine_schema, "procedure schema")
    validate_routine_name(obj.routine_name, "procedure name")
    types = {p.name: p.sql_type for p in obj.params}
    args = []
    for name, value in params:
        if not _PARAM_NAME_RE.match(name):
            raise SQLExecutionError(f"Invalid parameter name '{name}'")
        args.append(f"@{name} = {_literal(value, types.get(name, ''))}")
    proc = _quote_ident(obj.routine_schema) + "." + _quote_ident(obj.routine_name)
    return f"EXEC {proc}" + (" " + ", ".join(args) if args else "")


_PARAM_NAME_RE = re.compile(r"^[A-Za-z_@#$][A-Za-z0-9_@#$]{0,127}$")


def _bulk_insert(
    cursor: Any, temp: str, columns: list[VirtualColumn], rows: list[tuple[Any, ...]]
) -> None:
    if not rows:
        return
    types = [c.sql_type for c in columns]
    # SQL Server caps a VALUES list at 1000 rows.
    chunk = 1000
    for start in range(0, len(rows), chunk):
        values = ",".join(
            "(" + ",".join(_literal(v, types[i] if i < len(types) else "") for i, v in enumerate(row)) + ")"
            for row in rows[start:start + chunk]
        )
        cursor.execute(f"INSERT INTO {temp} VALUES {values}")


def _error_number(e: Exception) -> int | None:
    for candidate in (e, getattr(e, "cause", None), e.__cause__):
        if candidate is None:
            continue
        args = getattr(candidate, "args", ())
        if args and isinstance(args[0], int):
            return args[0]
        number = getattr(candidate, "number", None)
        if isinstance(number, int):
            return number
    return None


def _described(rows: list[Any]) -> list[dict[str, Any]] | None:
    """sys.dm_exec_describe_first_result_set* rows → columns, None on error."""
    if not rows or any(r[3] for r in rows) or any(r[1] is None for r in rows):
        return None
    return [
        {"name": r[0] or "", "sql_type": r[1], "nullable": bool(r[2])}
        for r in rows
    ]


def _mssql_type(type_name: str | None, max_length: int, precision: int, scale: int) -> str:
    t = (type_name or "").lower()
    if t in ("varchar", "char", "varbinary", "binary"):
        return f"{t}(max)" if max_length == -1 else f"{t}({max_length})"
    if t in ("nvarchar", "nchar"):
        return f"{t}(max)" if max_length == -1 else f"{t}({max_length // 2})"
    if t in ("decimal", "numeric"):
        return f"{t}({precision},{scale})"
    if t in ("datetime2", "datetimeoffset", "time"):
        return f"{t}({scale})"
    return t


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
