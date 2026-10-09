"""
SAP HANA Database Connector

Provides async SAP HANA connectivity using hdbcli wrapped in asyncio executor.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncGenerator

from sandbox.connectors.base import BaseConnector, QueryResult
from sandbox.connectors.host_policy import vet_destination
from sandbox.connectors.tls import resolve_ssl_mode, system_ca_file
from sandbox.core.exceptions import ConnectionError, SQLExecutionError
from sandbox.core.logging import get_logger

logger = get_logger(__name__)

_executor = ThreadPoolExecutor(max_workers=10)


def hana_tls_params(
    mode: str,
    ca_cert: str | None,
    *,
    connection_id: str | None = None,
    db_type: str | None = None,
) -> dict[str, Any]:
    """hdbcli connect properties for an SSL mode (see connectors/tls.py).

    hdbcli has no "TLS if available": a connection is encrypted or it is not,
    so ``allow``/``prefer`` cannot be honoured and are refused rather than
    quietly run as something else.
    """
    if mode == "disable":
        return {}
    if mode in ("allow", "prefer"):
        raise ConnectionError(
            f"SSL mode '{mode}' is not available for SAP HANA: the driver either "
            "encrypts or does not. Use 'disable' or 'require'. Not connecting.",
            connection_id=connection_id,
            db_type=db_type,
        )
    if mode == "require":
        return {"encrypt": True, "sslValidateCertificate": False}

    # verify-ca / verify-full: the chain is checked against the given CA, or
    # the system trust store. hdbcli takes PEM text or a file path here.
    trust_store = ca_cert or system_ca_file()
    if not trust_store:
        raise ConnectionError(
            f"SSL mode '{mode}' needs to verify the server certificate, but no CA "
            "certificate was given and this sandbox has no system trust store. "
            "Add the CA certificate to the connection. Not connecting.",
            connection_id=connection_id,
            db_type=db_type,
        )
    params: dict[str, Any] = {
        "encrypt": True,
        "sslValidateCertificate": True,
        "sslCryptoProvider": "openssl",
        "sslTrustStore": trust_store,
    }
    if mode == "verify-ca":
        # "*" accepts any host name; the chain is still verified.
        params["sslHostNameInCertificate"] = "*"
    return params


class SAPHANAConnector(BaseConnector[Any]):
    """
    SAP HANA connector using hdbcli.

    hdbcli is synchronous, so all operations are offloaded to a thread
    executor to remain compatible with the async BaseConnector interface.
    """

    async def connect(self) -> Any:
        """Create a new SAP HANA connection."""
        cfg = self.config
        tls_params = hana_tls_params(
            resolve_ssl_mode(cfg),
            cfg.ssl_ca_cert,
            connection_id=self.connection_id,
            db_type=self.db_type,
        )

        # Where this may point is decided in connectors/host_policy.py. The
        # host is still dialled by name: HANA Cloud routes on it, and hdbcli
        # exposes no socket to check.
        await vet_destination(cfg)

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
                conn_params.update(tls_params)

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
        """Get list of tables and views in the database."""
        return [e["name"] for e in await self.get_table_entries(conn, schema=schema)]

    async def get_table_entries(
        self, conn: Any, schema: str | None = None
    ) -> list[dict[str, Any]]:
        """Tables (SYS.TABLES) and views (SYS.VIEWS) as ``[{"name", "type"}]``."""
        schema = schema or self.config.schema_name
        where, args = _schema_filter(schema)

        def _get_entries() -> list[dict[str, Any]]:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT TABLE_NAME AS NAME, 'TABLE' AS KIND FROM SYS.TABLES WHERE {where}
                UNION ALL
                SELECT VIEW_NAME, 'VIEW' FROM SYS.VIEWS WHERE {where}
                ORDER BY 1
                """,
                args + args,
            )
            return [{"name": row[0], "type": row[1]} for row in cursor.fetchall()]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, _get_entries)

    async def get_columns(
        self, conn: Any, table: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        """Get column information for a table or view."""
        schema = schema or self.config.schema_name
        if schema:
            where, args = "SCHEMA_NAME = ?", (schema,)
        else:
            where, args = "1 = 1", ()

        def _get_columns() -> list[dict[str, Any]]:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE, DEFAULT_VALUE,
                       LENGTH, SCALE, POSITION
                FROM SYS.TABLE_COLUMNS WHERE {where} AND TABLE_NAME = ?
                UNION ALL
                SELECT COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE, DEFAULT_VALUE,
                       LENGTH, SCALE, POSITION
                FROM SYS.VIEW_COLUMNS WHERE {where} AND VIEW_NAME = ?
                ORDER BY 7
                """,
                args + (table,) + args + (table,),
            )
            return [_column_row(row) for row in cursor.fetchall()]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, _get_columns)

    async def get_all_columns(
        self, conn: Any, schema: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Batch-fetch columns for EVERY table and view in the schema in one query.

        Returns ``{table_name: [columns]}``. Without this the full-sync route
        pays one SYS.TABLE_COLUMNS round trip per table, each on its own
        physical connection.
        """
        schema = schema or self.config.schema_name
        where, args = _schema_filter(schema)

        def _get_all_columns() -> dict[str, list[dict[str, Any]]]:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE,
                       DEFAULT_VALUE, LENGTH, SCALE, POSITION
                FROM SYS.TABLE_COLUMNS WHERE {where}
                UNION ALL
                SELECT VIEW_NAME, COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE,
                       DEFAULT_VALUE, LENGTH, SCALE, POSITION
                FROM SYS.VIEW_COLUMNS WHERE {where}
                ORDER BY 1, 8
                """,
                args + args,
            )

            tables: dict[str, list[dict[str, Any]]] = {}
            for row in cursor.fetchall():
                tables.setdefault(row[0], []).append(_column_row(row[1:]))
            return tables

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, _get_all_columns)

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


def _schema_filter(schema: str | None) -> tuple[str, tuple[Any, ...]]:
    """WHERE fragment scoping SYS.* catalog views to one schema, or to all
    non-system schemas when the connection names none."""
    if schema:
        return "SCHEMA_NAME = ?", (schema,)
    return "SCHEMA_NAME NOT LIKE 'SYS%' AND SCHEMA_NAME NOT LIKE '_SYS%'", ()


def _column_row(row: Any) -> dict[str, Any]:
    """(COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE, DEFAULT_VALUE, LENGTH, SCALE, ...)"""
    return {
        "name": row[0],
        "type": row[1],
        "nullable": row[2] == "TRUE",
        "default": row[3],
        "max_length": row[4],
        "scale": row[5],
    }


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
