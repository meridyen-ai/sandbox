"""
MSSQL Database Connector

Provides async SQL Server connectivity using pymssql wrapped in asyncio executor.
"""

from __future__ import annotations

import asyncio
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

_executor = ThreadPoolExecutor(max_workers=10)


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
        conn = await loop.run_in_executor(_executor, _connect)

        # FreeTDS decodes every varchar with the server's default code page, so
        # a database on a different one (e.g. Turkish_CI_AS under a CP1252
        # server) needs its rows re-decoded. Resolved once per connection.
        self._codepage = await loop.run_in_executor(_executor, detect_codepage, conn)

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
        """Close a SQL Server connection."""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(_executor, conn.close)
        except Exception as e:
            self._logger.warning(
                "connection_close_error",
                connection_id=self.connection_id,
                error=str(e),
            )

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
        return await loop.run_in_executor(_executor, _execute)

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
            cursor = await loop.run_in_executor(_executor, _prepare, query, parameters)
            while True:
                batch = await loop.run_in_executor(_executor, _fetch_batch, cursor)
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
        return await loop.run_in_executor(_executor, _get_tables)

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
        return await loop.run_in_executor(_executor, _get_columns)

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
        return await loop.run_in_executor(_executor, _test)


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
