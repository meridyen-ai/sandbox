"""
MySQL Database Connector

Provides async MySQL connectivity using aiomysql.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

import aiomysql
from aiomysql import Connection, Cursor

from sandbox.connectors.base import BaseConnector, QueryResult
from sandbox.core.config import DatabaseConnectionConfig
from sandbox.core.exceptions import ConnectionError, SQLExecutionError
from sandbox.core.logging import get_logger

logger = get_logger(__name__)


class MySQLConnector(BaseConnector[Connection]):
    """
    MySQL connector using aiomysql.

    Features:
    - Native async support
    - Connection pooling
    - SSL/TLS support
    - Prepared statements
    """

    async def connect(self) -> Connection:
        """Create a new MySQL connection."""
        cfg = self.config

        try:
            # Build SSL context if enabled
            ssl_context = None
            if cfg.ssl_enabled:
                import ssl
                ssl_context = ssl.create_default_context()
                if cfg.ssl_ca_cert:
                    ssl_context.load_verify_locations(cfg.ssl_ca_cert)
                else:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

            conn = await aiomysql.connect(
                host=cfg.host,
                port=cfg.port,
                db=cfg.database,
                user=cfg.username,
                password=cfg.password.get_secret_value(),
                ssl=ssl_context,
                connect_timeout=cfg.connection_timeout,
                autocommit=True,
                charset="utf8mb4",
            )

            self._logger.debug(
                "connection_created",
                connection_id=self.connection_id,
                host=cfg.host,
                database=cfg.database,
            )

            return conn

        except aiomysql.OperationalError as e:
            error_code = e.args[0] if e.args else 0

            if error_code == 1045:  # Access denied
                raise ConnectionError(
                    "Invalid database credentials",
                    connection_id=self.connection_id,
                    db_type=self.db_type,
                )
            elif error_code == 1049:  # Unknown database
                raise ConnectionError(
                    f"Database '{cfg.database}' does not exist",
                    connection_id=self.connection_id,
                    db_type=self.db_type,
                )
            elif error_code == 2003:  # Can't connect
                raise ConnectionError(
                    f"Cannot connect to MySQL server at {cfg.host}:{cfg.port}",
                    connection_id=self.connection_id,
                    db_type=self.db_type,
                )
            else:
                raise ConnectionError(
                    f"Failed to connect to MySQL: {e}",
                    connection_id=self.connection_id,
                    db_type=self.db_type,
                    cause=e,
                )
        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to MySQL: {e}",
                connection_id=self.connection_id,
                db_type=self.db_type,
                cause=e,
            )

    async def close_connection(self, conn: Connection) -> None:
        """Close a MySQL connection."""
        try:
            conn.close()
        except Exception as e:
            self._logger.warning(
                "connection_close_error",
                connection_id=self.connection_id,
                error=str(e),
            )

    async def execute(
        self,
        conn: Connection,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a query and return results."""
        try:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Convert named parameters if needed
                if parameters:
                    query, args = self._convert_parameters(query, parameters)
                    await cursor.execute(query, args)
                else:
                    await cursor.execute(query)

                # Fetch results
                rows_raw = await cursor.fetchall()

                # Extract column info
                if cursor.description:
                    columns = [desc[0] for desc in cursor.description]
                    column_types = [self._get_type_name(desc[1]) for desc in cursor.description]
                else:
                    columns = []
                    column_types = []

                # Convert dict rows to tuples
                rows = [tuple(row.values()) for row in rows_raw]

                return QueryResult(
                    columns=columns,
                    column_types=column_types,
                    rows=rows,
                    row_count=len(rows),
                    affected_rows=cursor.rowcount,
                )

        except aiomysql.ProgrammingError as e:
            raise SQLExecutionError(
                f"SQL error: {e}",
                query=query,
            )
        except aiomysql.OperationalError as e:
            raise SQLExecutionError(
                f"Query execution failed: {e}",
                query=query,
            )
        except Exception as e:
            raise SQLExecutionError(
                f"Query execution failed: {e}",
                query=query,
                cause=e,
            )

    async def execute_streaming(
        self,
        conn: Connection,
        query: str,
        parameters: dict[str, Any] | None = None,
        batch_size: int = 1000,
    ) -> AsyncGenerator[list[tuple[Any, ...]], None]:
        """Execute a query and stream results in batches."""
        try:
            # Use SSCursor for server-side cursor (streaming)
            async with conn.cursor(aiomysql.SSCursor) as cursor:
                if parameters:
                    query, args = self._convert_parameters(query, parameters)
                    await cursor.execute(query, args)
                else:
                    await cursor.execute(query)

                while True:
                    batch = await cursor.fetchmany(batch_size)
                    if not batch:
                        break
                    yield batch

        except Exception as e:
            raise SQLExecutionError(
                f"Streaming query failed: {e}",
                query=query,
                cause=e,
            )

    async def get_tables(self, conn: Connection, schema: str | None = None) -> list[str]:
        """Get list of tables in the database."""
        schema = schema or self.config.database

        query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """

        async with conn.cursor() as cursor:
            await cursor.execute(query, (schema,))
            result = await cursor.fetchall()
            return [r[0] for r in result]

    async def get_columns(
        self, conn: Connection, table: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        """Get column information for a table."""
        schema = schema or self.config.database

        query = """
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length,
                numeric_precision,
                numeric_scale,
                column_key
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ordinal_position
        """

        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(query, (schema, table))
            result = await cursor.fetchall()
            return [
                {
                    "name": r["column_name"],
                    "type": r["data_type"],
                    "nullable": r["is_nullable"] == "YES",
                    "default": r["column_default"],
                    "max_length": r["character_maximum_length"],
                    "precision": r["numeric_precision"],
                    "scale": r["numeric_scale"],
                    "is_primary_key": r["column_key"] == "PRI",
                }
                for r in result
            ]

    async def test_connection(self, conn: Connection) -> bool:
        """Test if connection is valid."""
        try:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1")
                await cursor.fetchone()
                return True
        except Exception:
            return False

    def _convert_parameters(
        self, query: str, parameters: dict[str, Any]
    ) -> tuple[str, tuple[Any, ...]]:
        """
        Convert named parameters to positional.

        MySQL uses %s for parameters.
        """
        import re

        # Find all named parameters (:name)
        pattern = r":(\w+)"
        matches = re.findall(pattern, query)

        # Build positional args in order of appearance
        args = []
        for match in matches:
            args.append(parameters.get(match))

        # Replace named params with %s
        converted_query = re.sub(pattern, "%s", query)

        return converted_query, tuple(args)

    @staticmethod
    def _get_type_name(type_code: int) -> str:
        """Convert MySQL type code to type name."""
        # Common MySQL type codes
        type_map = {
            0: "DECIMAL",
            1: "TINY",
            2: "SHORT",
            3: "LONG",
            4: "FLOAT",
            5: "DOUBLE",
            6: "NULL",
            7: "TIMESTAMP",
            8: "LONGLONG",
            9: "INT24",
            10: "DATE",
            11: "TIME",
            12: "DATETIME",
            13: "YEAR",
            14: "NEWDATE",
            15: "VARCHAR",
            16: "BIT",
            246: "NEWDECIMAL",
            247: "ENUM",
            248: "SET",
            249: "TINY_BLOB",
            250: "MEDIUM_BLOB",
            251: "LONG_BLOB",
            252: "BLOB",
            253: "VAR_STRING",
            254: "STRING",
            255: "GEOMETRY",
        }
        return type_map.get(type_code, "UNKNOWN")
