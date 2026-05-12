"""
SAP HANA Database Connector

Provides async SAP HANA connectivity using hdbcli wrapped in asyncio executor.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncGenerator

from sandbox.connectors.base import BaseConnector, QueryResult
from sandbox.core.exceptions import ConnectionError, SQLExecutionError
from sandbox.core.logging import get_logger

logger = get_logger(__name__)

_executor = ThreadPoolExecutor(max_workers=10)


class SAPHANAConnector(BaseConnector[Any]):
    """
    SAP HANA connector using hdbcli.

    hdbcli is synchronous, so all operations are offloaded to a thread
    executor to remain compatible with the async BaseConnector interface.
    """

    async def connect(self) -> Any:
        """Create a new SAP HANA connection."""
        cfg = self.config

        def _connect() -> Any:
            from hdbcli import dbapi
            try:
                conn_params = {
                    "address": cfg.host,
                    "port": cfg.port,
                    "user": cfg.username,
                    "password": cfg.password.get_secret_value(),
                }
                if cfg.database:
                    conn_params["databaseName"] = cfg.database
                if cfg.schema_name:
                    conn_params["currentSchema"] = cfg.schema_name
                if cfg.ssl_enabled:
                    conn_params["encrypt"] = True
                    conn_params["sslValidateCertificate"] = False

                return dbapi.connect(**conn_params)
            except Exception as e:
                raise ConnectionError(
                    f"Failed to connect to SAP HANA: {e}",
                    connection_id=cfg.id,
                    db_type="saphana",
                    cause=e,
                )

        loop = asyncio.get_event_loop()
        conn = await loop.run_in_executor(_executor, _connect)

        self._logger.debug(
            "connection_created",
            connection_id=self.connection_id,
            host=cfg.host,
            database=cfg.database,
        )

        return conn

    async def close_connection(self, conn: Any) -> None:
        """Close a SAP HANA connection."""
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
                    column_types = [str(desc[1]) for desc in cursor.description]
                    rows = cursor.fetchall() or []
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
        """Get list of tables in the database."""
        schema = schema or self.config.schema_name

        def _get_tables() -> list[str]:
            cursor = conn.cursor()
            if schema:
                cursor.execute(
                    """
                    SELECT TABLE_NAME
                    FROM SYS.TABLES
                    WHERE SCHEMA_NAME = ?
                    ORDER BY TABLE_NAME
                    """,
                    (schema,),
                )
            else:
                cursor.execute(
                    """
                    SELECT TABLE_NAME
                    FROM SYS.TABLES
                    WHERE SCHEMA_NAME NOT LIKE 'SYS%' AND SCHEMA_NAME NOT LIKE '_SYS%'
                    ORDER BY TABLE_NAME
                    """
                )
            return [row[0] for row in cursor.fetchall()]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, _get_tables)

    async def get_columns(
        self, conn: Any, table: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        """Get column information for a table."""
        schema = schema or self.config.schema_name

        def _get_columns() -> list[dict[str, Any]]:
            cursor = conn.cursor()
            if schema:
                cursor.execute(
                    """
                    SELECT
                        COLUMN_NAME,
                        DATA_TYPE_NAME,
                        IS_NULLABLE,
                        DEFAULT_VALUE,
                        LENGTH,
                        SCALE
                    FROM SYS.TABLE_COLUMNS
                    WHERE SCHEMA_NAME = ? AND TABLE_NAME = ?
                    ORDER BY POSITION
                    """,
                    (schema, table),
                )
            else:
                cursor.execute(
                    """
                    SELECT
                        COLUMN_NAME,
                        DATA_TYPE_NAME,
                        IS_NULLABLE,
                        DEFAULT_VALUE,
                        LENGTH,
                        SCALE
                    FROM SYS.TABLE_COLUMNS
                    WHERE TABLE_NAME = ?
                    ORDER BY POSITION
                    """,
                    (table,),
                )
            return [
                {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2] == "TRUE",
                    "default": row[3],
                    "max_length": row[4],
                    "scale": row[5],
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
                cursor.execute("SELECT 1 FROM SYS.DUMMY")
                cursor.fetchone()
                return True
            except Exception:
                return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, _test)


def _convert_parameters(
    query: str, parameters: dict[str, Any]
) -> tuple[str, tuple[Any, ...]]:
    """Convert named parameters (:name) to hdbcli positional (?)."""
    import re

    pattern = r":(\w+)"
    matches = re.findall(pattern, query)
    args = [parameters.get(m) for m in matches]
    converted_query = re.sub(pattern, "?", query)
    return converted_query, tuple(args)
