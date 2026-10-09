"""
MySQL Database Connector

Provides async MySQL connectivity using aiomysql.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator

import aiomysql
from aiomysql import Connection, Cursor
from pymysql.constants import CLIENT

from sandbox.connectors.base import BaseConnector, QueryResult
from sandbox.connectors.host_policy import verify_peer, vet_destination
from sandbox.connectors.tls import build_ssl_context, resolve_ssl_mode
from sandbox.core.config import DatabaseConnectionConfig
from sandbox.core.exceptions import ConnectionError, SQLExecutionError
from sandbox.core.logging import get_logger

logger = get_logger(__name__)

# Modes that must never run in plaintext.
_TLS_REQUIRED_MODES = ("require", "verify-ca", "verify-full")


class _TLSNotEstablished(Exception):
    """The server did not offer TLS to a connection that insists on it."""


class _TLSRequiredConnection(Connection):
    """A connection that stops before signing in when the server has no TLS.

    aiomysql sends the credentials in plaintext when the server's greeting does
    not advertise TLS, even with an SSL context set. Anyone on the path can
    strip that flag, so the check has to happen before authentication.
    """

    async def _request_authentication(self) -> None:
        if not self.server_capabilities & CLIENT.SSL:
            raise _TLSNotEstablished()
        await super()._request_authentication()


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

        # MySQL's own names for the modes (see connectors/tls.py):
        #   disable            DISABLED
        #   allow, prefer      PREFERRED - TLS when the server offers it
        #   require            REQUIRED  - TLS or no connection, unverified
        #   verify-ca / -full  VERIFY_CA / VERIFY_IDENTITY
        ssl_mode = resolve_ssl_mode(cfg)
        ssl_context = build_ssl_context(
            ssl_mode,
            cfg.ssl_ca_cert,
            connection_id=self.connection_id,
            db_type=self.db_type,
        )
        tls_required = ssl_mode in _TLS_REQUIRED_MODES

        # Where this may point is decided in connectors/host_policy.py. Without
        # TLS nothing needs the host name again, so the checked addresses are
        # dialled in order. With TLS the name is needed for the certificate
        # check, so the name is dialled and the address that answered is
        # checked below.
        vetted = await vet_destination(cfg)
        dial_hosts = (
            list(vetted.addresses) if vetted.enforced and ssl_context is None else [cfg.host]
        )

        try:
            connect_args: dict[str, Any] = dict(
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
            if tls_required:
                # What aiomysql.connect() does, with the class that refuses
                # to sign in over plaintext.
                conn = _TLSRequiredConnection(**connect_args)
                await conn._connect()
            else:
                for attempt, dial_host in enumerate(dial_hosts, start=1):
                    try:
                        conn = await aiomysql.connect(**{**connect_args, "host": dial_host})
                        break
                    except aiomysql.OperationalError as e:
                        # 2003: nothing answered at this address; the next may.
                        if attempt == len(dial_hosts) or (e.args[0] if e.args else 0) != 2003:
                            raise

            writer = getattr(conn, "_writer", None)  # aiomysql's asyncio stream
            try:
                verify_peer(
                    cfg, vetted, writer.transport.get_extra_info("peername") if writer else None
                )
            except ConnectionError:
                conn.close()
                raise

            # aiomysql only upgrades to TLS when the server advertises it and
            # otherwise carries on in plaintext. For a mode that insists on
            # TLS the session must really be encrypted, whatever the driver did.
            if tls_required and not getattr(conn, "_secure", False):
                conn.close()
                raise _TLSNotEstablished()

            self._logger.debug(
                "connection_created",
                connection_id=self.connection_id,
                host=cfg.host,
                database=cfg.database,
            )

            return conn

        except ConnectionError:
            raise
        except _TLSNotEstablished:
            raise ConnectionError(
                f"SSL mode '{ssl_mode}' needs an encrypted link, but the MySQL server at "
                f"{cfg.host}:{cfg.port} does not offer TLS. Not connecting.",
                connection_id=self.connection_id,
                db_type=self.db_type,
            )
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

    # Set once a server has answered START TRANSACTION READ ONLY with "no such
    # syntax": a MySQL-compatible engine without read-only transactions.
    _read_only_unsupported: bool = False
    # How long ending the transaction may take before the connection is dropped.
    _END_TRANSACTION_TIMEOUT_S = 5.0

    async def _end_transaction(self, conn: Connection, statement: str) -> None:
        async with conn.cursor() as cursor:
            await cursor.execute(statement)

    async def execute_read_only(
        self,
        conn: Connection,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a caller's query inside a READ ONLY transaction.

        The server then refuses every change to a table the SQL validator did
        not recognise, including inside a function the query calls. The
        connection is reused, so the transaction is always ended here; when
        that cannot be done (the caller's timeout cancelled the query, or the
        server no longer answers) the connection is dropped and the next query
        opens a new one.
        """
        if self._read_only_unsupported:
            return await self.execute(conn, query, parameters)

        try:
            async with conn.cursor() as cursor:
                await cursor.execute("START TRANSACTION READ ONLY")
        except (aiomysql.ProgrammingError, aiomysql.NotSupportedError) as e:
            self._read_only_unsupported = True
            self._logger.warning(
                "read_only_transaction_unsupported",
                connection_id=self.connection_id,
                error=str(e),
            )
            return await self.execute(conn, query, parameters)
        except Exception as e:
            raise SQLExecutionError(
                f"Query execution failed: {e}",
                query=query,
                cause=e,
            )

        try:
            result = await self.execute(conn, query, parameters)
        except Exception:
            try:
                await asyncio.wait_for(
                    self._end_transaction(conn, "ROLLBACK"),
                    timeout=self._END_TRANSACTION_TIMEOUT_S,
                )
            except Exception:
                conn.close()
            except BaseException:
                conn.close()
                raise
            raise
        except BaseException:
            conn.close()
            raise

        try:
            await asyncio.wait_for(
                self._end_transaction(conn, "COMMIT"),
                timeout=self._END_TRANSACTION_TIMEOUT_S,
            )
        except Exception as e:
            conn.close()
            raise SQLExecutionError(
                f"Query execution failed: {e}",
                query=query,
                cause=e,
            )
        except BaseException:
            conn.close()
            raise
        return result

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
        """Get list of tables and views in the database."""
        return [e["name"] for e in await self.get_table_entries(conn, schema=schema)]

    async def get_table_entries(
        self, conn: Connection, schema: str | None = None
    ) -> list[dict[str, Any]]:
        """Tables and views as ``[{"name", "type"}]`` (TABLE / VIEW)."""
        schema = schema or self.config.database

        query = """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY table_name
        """

        async with conn.cursor() as cursor:
            await cursor.execute(query, (schema,))
            result = await cursor.fetchall()
            return [
                {"name": r[0], "type": "VIEW" if r[1] == "VIEW" else "TABLE"}
                for r in result
            ]

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

    async def get_all_columns(
        self, conn: Connection, schema: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Batch-fetch columns for EVERY table in the schema in one query.

        Returns ``{table_name: [columns]}``. Without this the full-sync route
        falls back to one INFORMATION_SCHEMA round trip per table, on its own
        physical connection — the fan-out that made a few hundred tables take
        minutes. Foreign keys come from KEY_COLUMN_USAGE in a second query
        rather than a join, because joining it against every column row makes
        MySQL materialise the whole constraint view per table.
        """
        schema = schema or self.config.database

        columns_query = """
            SELECT
                table_name,
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
            ORDER BY table_name, ordinal_position
        """

        fk_query = """
            SELECT
                table_name,
                column_name,
                referenced_table_schema,
                referenced_table_name,
                referenced_column_name
            FROM information_schema.key_column_usage
            WHERE table_schema = %s
              AND referenced_table_name IS NOT NULL
        """

        async with conn.cursor(aiomysql.DictCursor) as cursor:
            await cursor.execute(columns_query, (schema,))
            rows = await cursor.fetchall()
            await cursor.execute(fk_query, (schema,))
            fk_rows = await cursor.fetchall()

        # (table, column) -> "schema.table.column"
        fks: dict[tuple[str, str], str] = {}
        for r in fk_rows:
            fks.setdefault(
                (r["table_name"], r["column_name"]),
                f'{r["referenced_table_schema"]}.{r["referenced_table_name"]}'
                f'.{r["referenced_column_name"]}',
            )

        tables: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            key = (r["table_name"], r["column_name"])
            foreign_table = fks.get(key)
            tables.setdefault(r["table_name"], []).append({
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"] == "YES",
                "default": r["column_default"],
                "max_length": r["character_maximum_length"],
                "precision": r["numeric_precision"],
                "scale": r["numeric_scale"],
                "is_primary_key": r["column_key"] == "PRI",
                "is_unique": r["column_key"] in ("PRI", "UNI"),
                "is_foreign_key": foreign_table is not None,
                "foreign_table": foreign_table,
            })
        return tables

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
