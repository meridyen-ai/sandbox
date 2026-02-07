"""
PostgreSQL Database Connector

Provides async PostgreSQL connectivity using asyncpg.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

import asyncpg
from asyncpg import Connection, Pool

from sandbox.connectors.base import BaseConnector, QueryResult
from sandbox.core.config import DatabaseConnectionConfig
from sandbox.core.exceptions import ConnectionError, SQLExecutionError
from sandbox.core.logging import get_logger

logger = get_logger(__name__)


class PostgreSQLConnector(BaseConnector[Connection]):
    """
    PostgreSQL connector using asyncpg.

    Features:
    - Native async support
    - Prepared statements
    - Connection pooling
    - SSL/TLS support
    """

    async def connect(self) -> Connection:
        """Create a new PostgreSQL connection."""
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
                    # Allow self-signed certs in development
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

            conn = await asyncpg.connect(
                host=cfg.host,
                port=cfg.port,
                database=cfg.database,
                user=cfg.username,
                password=cfg.password.get_secret_value(),
                ssl=ssl_context,
                timeout=cfg.connection_timeout,
                command_timeout=cfg.query_timeout,
            )

            # Set search path if schema specified
            if cfg.schema_name:
                await conn.execute(f"SET search_path TO {cfg.schema_name}, public")

            self._logger.debug(
                "connection_created",
                connection_id=self.connection_id,
                host=cfg.host,
                database=cfg.database,
            )

            return conn

        except asyncpg.InvalidPasswordError:
            raise ConnectionError(
                "Invalid database credentials",
                connection_id=self.connection_id,
                db_type=self.db_type,
            )
        except asyncpg.InvalidCatalogNameError:
            raise ConnectionError(
                f"Database '{cfg.database}' does not exist",
                connection_id=self.connection_id,
                db_type=self.db_type,
            )
        except Exception as e:
            raise ConnectionError(
                f"Failed to connect to PostgreSQL: {e}",
                connection_id=self.connection_id,
                db_type=self.db_type,
                cause=e,
            )

    async def close_connection(self, conn: Connection) -> None:
        """Close a PostgreSQL connection."""
        try:
            await conn.close()
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
            # Convert named parameters to positional if needed
            if parameters:
                query, args = self._convert_parameters(query, parameters)
            else:
                args = []

            # Execute query
            stmt = await conn.prepare(query)
            records = await stmt.fetch(*args)

            # Extract column info
            columns = [attr.name for attr in stmt.get_attributes()]
            column_types = [str(attr.type) for attr in stmt.get_attributes()]

            # Convert records to tuples
            rows = [tuple(r) for r in records]

            return QueryResult(
                columns=columns,
                column_types=column_types,
                rows=rows,
                row_count=len(rows),
            )

        except asyncpg.PostgresSyntaxError as e:
            raise SQLExecutionError(
                f"SQL syntax error: {e}",
                query=query,
            )
        except asyncpg.UndefinedTableError as e:
            raise SQLExecutionError(
                f"Table not found: {e}",
                query=query,
            )
        except asyncpg.UndefinedColumnError as e:
            raise SQLExecutionError(
                f"Column not found: {e}",
                query=query,
            )
        except asyncpg.InsufficientPrivilegeError as e:
            raise SQLExecutionError(
                f"Insufficient privileges: {e}",
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
            if parameters:
                query, args = self._convert_parameters(query, parameters)
            else:
                args = []

            # Use cursor for streaming
            async with conn.transaction():
                cursor = await conn.cursor(query, *args)

                while True:
                    batch = await cursor.fetch(batch_size)
                    if not batch:
                        break
                    yield [tuple(r) for r in batch]

        except Exception as e:
            raise SQLExecutionError(
                f"Streaming query failed: {e}",
                query=query,
                cause=e,
            )

    async def get_tables(self, conn: Connection, schema: str | None = None) -> list[str]:
        """Get list of tables in the database."""
        schema = schema or self.config.schema_name or "public"

        query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = $1
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """

        result = await conn.fetch(query, schema)
        return [r["table_name"] for r in result]

    async def get_columns(
        self, conn: Connection, table: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        """Get column information for a table."""
        schema = schema or self.config.schema_name or "public"

        query = """
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length,
                numeric_precision,
                numeric_scale
            FROM information_schema.columns
            WHERE table_schema = $1
              AND table_name = $2
            ORDER BY ordinal_position
        """

        result = await conn.fetch(query, schema, table)
        return [
            {
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"] == "YES",
                "default": r["column_default"],
                "max_length": r["character_maximum_length"],
                "precision": r["numeric_precision"],
                "scale": r["numeric_scale"],
            }
            for r in result
        ]

    async def test_connection(self, conn: Connection) -> bool:
        """Test if connection is valid."""
        try:
            await conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    def _convert_parameters(
        self, query: str, parameters: dict[str, Any]
    ) -> tuple[str, list[Any]]:
        """
        Convert named parameters to positional.

        asyncpg uses $1, $2, etc. for parameters.
        """
        import re

        # Find all named parameters
        pattern = r":(\w+)"
        matches = re.findall(pattern, query)

        # Build positional args
        args = []
        param_map: dict[str, int] = {}

        for match in matches:
            if match not in param_map:
                param_map[match] = len(args) + 1
                args.append(parameters.get(match))

        # Replace named params with positional
        def replace_param(m: re.Match) -> str:
            name = m.group(1)
            return f"${param_map[name]}"

        converted_query = re.sub(pattern, replace_param, query)

        return converted_query, args
