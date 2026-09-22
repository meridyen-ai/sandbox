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

# asyncpg reports internal type names; show the SQL spelling users know.
_PG_TYPE_NAMES = {
    "int2": "smallint",
    "int4": "integer",
    "int8": "bigint",
    "float4": "real",
    "float8": "double precision",
    "bool": "boolean",
    "varchar": "character varying",
    "bpchar": "character",
    "timestamptz": "timestamp with time zone",
    "timestamp": "timestamp without time zone",
    "timetz": "time with time zone",
}


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
            # Build SSL context if enabled, explicitly disable if not
            ssl_context = False  # Explicitly disable SSL negotiation
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

            # Enable TCP keepalives on the underlying socket. asyncpg's
            # command_timeout is enforced by sending a cancel request over the
            # SAME socket, so when a remote peer (e.g. a cross-internet ERP
            # behind NAT/a firewall) silently drops an idle pooled connection,
            # both the query AND its cancel block forever on a dead socket and
            # the connection wedges indefinitely. Keepalives let the kernel
            # detect the dead peer within ~seconds and error the socket, and
            # TCP_USER_TIMEOUT bounds how long an unacked send (the cancel
            # included) waits before the socket fails. Best-effort: skip
            # silently on platforms/sockets that don't support an option.
            self._enable_tcp_keepalive(conn)

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

    # TCP keepalive tuning (seconds). Detect a dead peer in ~15s+3*5s=30s
    # rather than never; TCP_USER_TIMEOUT caps an unacked send at 30s.
    _KEEPALIVE_IDLE_S = 15
    _KEEPALIVE_INTERVAL_S = 5
    _KEEPALIVE_COUNT = 3
    _TCP_USER_TIMEOUT_MS = 30_000

    def _enable_tcp_keepalive(self, conn: Connection) -> None:
        """Turn on TCP keepalives for a connection's socket (best-effort)."""
        import socket

        try:
            transport = conn._transport  # asyncpg exposes the asyncio transport
            sock = transport.get_extra_info("socket") if transport else None
        except Exception:
            sock = None
        if sock is None:
            return

        def _set(level: int, optname: str, value: int) -> None:
            opt = getattr(socket, optname, None)
            if opt is None:  # option not defined on this platform
                return
            try:
                sock.setsockopt(level, opt, value)
            except (OSError, PermissionError):
                pass  # unsupported for this socket family; keep the others

        _set(socket.SOL_SOCKET, "SO_KEEPALIVE", 1)
        _set(socket.IPPROTO_TCP, "TCP_KEEPIDLE", self._KEEPALIVE_IDLE_S)
        _set(socket.IPPROTO_TCP, "TCP_KEEPINTVL", self._KEEPALIVE_INTERVAL_S)
        _set(socket.IPPROTO_TCP, "TCP_KEEPCNT", self._KEEPALIVE_COUNT)
        # Linux-only: bound total time an unacked segment may stay in-flight.
        _set(socket.IPPROTO_TCP, "TCP_USER_TIMEOUT", self._TCP_USER_TIMEOUT_MS)

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
            column_types = [
                getattr(attr.type, 'name', str(attr.type))
                for attr in stmt.get_attributes()
            ]

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

    # relkind → catalog kind: views and materialized views are VIEWs;
    # plain, partitioned and foreign tables are TABLEs.
    _VIEW_RELKINDS = ("v", "m")

    async def get_tables(self, conn: Connection, schema: str | None = None) -> list[str]:
        """Get list of tables and views in the database."""
        return [e["name"] for e in await self.get_table_entries(conn, schema=schema)]

    async def get_table_entries(
        self, conn: Connection, schema: str | None = None
    ) -> list[dict[str, Any]]:
        """Tables and views as ``[{"name", "type"}]`` (TABLE / VIEW).

        Read from pg_class rather than information_schema.tables because the
        latter never lists materialized views. has_table_privilege keeps the
        set limited to what the login can read, matching information_schema.
        """
        schema = schema or self.config.schema_name or "public"

        query = """
            SELECT c.relname AS name, c.relkind::text AS relkind
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = $1
              AND c.relkind IN ('r', 'p', 'f', 'v', 'm')
              AND NOT c.relispartition
              AND has_table_privilege(c.oid, 'SELECT')
            ORDER BY c.relname
        """

        result = await conn.fetch(query, schema)
        return [
            {
                "name": r["name"],
                "type": "VIEW" if r["relkind"] in self._VIEW_RELKINDS else "TABLE",
            }
            for r in result
        ]

    async def get_columns(
        self, conn: Connection, table: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        """Get column information for a table."""
        schema = schema or self.config.schema_name or "public"

        query = """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.character_maximum_length,
                c.numeric_precision,
                c.numeric_scale,
                CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_primary_key,
                CASE WHEN uq.column_name IS NOT NULL THEN true ELSE false END AS is_unique,
                CASE WHEN fk.column_name IS NOT NULL THEN true ELSE false END AS is_foreign_key,
                fk.foreign_table_schema,
                fk.foreign_table_name,
                fk.foreign_column_name
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = $1
                    AND tc.table_name = $2
                    AND tc.constraint_type = 'PRIMARY KEY'
            ) pk ON pk.column_name = c.column_name
            LEFT JOIN (
                SELECT DISTINCT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.table_schema = $1
                    AND tc.table_name = $2
                    AND tc.constraint_type = 'UNIQUE'
            ) uq ON uq.column_name = c.column_name
            LEFT JOIN (
                SELECT
                    kcu.column_name,
                    ccu.table_schema AS foreign_table_schema,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON tc.constraint_name = ccu.constraint_name
                    AND tc.table_schema = ccu.table_schema
                WHERE tc.table_schema = $1
                    AND tc.table_name = $2
                    AND tc.constraint_type = 'FOREIGN KEY'
            ) fk ON fk.column_name = c.column_name
            WHERE c.table_schema = $1
              AND c.table_name = $2
            ORDER BY c.ordinal_position
        """

        result = await conn.fetch(query, schema, table)
        if not result:
            # information_schema.columns never covers materialized views.
            return (await self._matview_columns(conn, schema, table)).get(table, [])
        return [
            {
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"] == "YES",
                "default": r["column_default"],
                "max_length": r["character_maximum_length"],
                "precision": r["numeric_precision"],
                "scale": r["numeric_scale"],
                "is_primary_key": r["is_primary_key"],
                "is_unique": r["is_unique"],
                "is_foreign_key": r["is_foreign_key"],
                "foreign_table": (
                    f"{r['foreign_table_schema']}.{r['foreign_table_name']}.{r['foreign_column_name']}"
                    if r["is_foreign_key"] else None
                ),
            }
            for r in result
        ]

    async def get_all_columns(
        self, conn: Connection, schema: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Batch-fetch columns for ALL tables in one query.
        Returns dict: table_name -> [columns].
        This is ~50-100x faster than calling get_columns() per table.
        """
        schema = schema or self.config.schema_name or "public"

        # Constraint flags come from pg_catalog, NOT the information_schema
        # constraint views: constraint_column_usage / key_column_usage are
        # per-row-privilege-checked UNION views that take 80-90+ seconds on a
        # database with a few hundred constraints (observed on meridyen_os),
        # which is what made schema full-sync time out. The pg_catalog rewrite
        # returns byte-identical rows in ~30ms.
        query = """
            SELECT
                c.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.character_maximum_length,
                c.numeric_precision,
                c.numeric_scale,
                c.ordinal_position,
                (pk.column_name IS NOT NULL) AS is_primary_key,
                (uq.column_name IS NOT NULL) AS is_unique,
                (fk.column_name IS NOT NULL) AS is_foreign_key,
                fk.foreign_table_schema,
                fk.foreign_table_name,
                fk.foreign_column_name
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT t.relname AS table_name, a.attname AS column_name
                FROM pg_constraint con
                JOIN pg_class t ON t.oid = con.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                CROSS JOIN LATERAL unnest(con.conkey) AS ck(attnum)
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ck.attnum
                WHERE con.contype = 'p' AND n.nspname = $1
            ) pk ON pk.table_name = c.table_name AND pk.column_name = c.column_name
            LEFT JOIN (
                SELECT DISTINCT t.relname AS table_name, a.attname AS column_name
                FROM pg_constraint con
                JOIN pg_class t ON t.oid = con.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                CROSS JOIN LATERAL unnest(con.conkey) AS ck(attnum)
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ck.attnum
                WHERE con.contype = 'u' AND n.nspname = $1
            ) uq ON uq.table_name = c.table_name AND uq.column_name = c.column_name
            LEFT JOIN (
                SELECT DISTINCT ON (t.relname, a.attname)
                    t.relname AS table_name,
                    a.attname AS column_name,
                    fn.nspname AS foreign_table_schema,
                    ft.relname AS foreign_table_name,
                    fa.attname AS foreign_column_name
                FROM pg_constraint con
                JOIN pg_class t ON t.oid = con.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_class ft ON ft.oid = con.confrelid
                JOIN pg_namespace fn ON fn.oid = ft.relnamespace
                CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS ck(attnum, ord)
                JOIN LATERAL unnest(con.confkey) WITH ORDINALITY AS cfk(attnum, ord)
                    ON cfk.ord = ck.ord
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ck.attnum
                JOIN pg_attribute fa ON fa.attrelid = ft.oid AND fa.attnum = cfk.attnum
                WHERE con.contype = 'f' AND n.nspname = $1
            ) fk ON fk.table_name = c.table_name AND fk.column_name = c.column_name
            WHERE c.table_schema = $1
              AND c.table_name IN (
                  SELECT tc.relname
                  FROM pg_class tc
                  JOIN pg_namespace tn ON tn.oid = tc.relnamespace
                  WHERE tn.nspname = $1 AND tc.relkind IN ('r', 'p', 'f', 'v')
              )
            ORDER BY c.table_name, c.ordinal_position
        """

        result = await conn.fetch(query, schema)

        tables: dict[str, list[dict[str, Any]]] = {}
        for r in result:
            table_name = r["table_name"]
            if table_name not in tables:
                tables[table_name] = []
            tables[table_name].append({
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"] == "YES",
                "default": r["column_default"],
                "max_length": r["character_maximum_length"],
                "precision": r["numeric_precision"],
                "scale": r["numeric_scale"],
                "is_primary_key": r["is_primary_key"],
                "is_unique": r["is_unique"],
                "is_foreign_key": r["is_foreign_key"],
                "foreign_table": (
                    f"{r['foreign_table_schema']}.{r['foreign_table_name']}.{r['foreign_column_name']}"
                    if r["is_foreign_key"] else None
                ),
            })

        # Materialized views are invisible to information_schema.columns.
        for name, cols in (await self._matview_columns(conn, schema)).items():
            tables.setdefault(name, cols)

        return tables

    async def _matview_columns(
        self, conn: Connection, schema: str, table: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        """Columns of materialized views, read straight from pg_attribute."""
        query = """
            SELECT c.relname AS table_name,
                   a.attname AS column_name,
                   format_type(a.atttypid, a.atttypmod) AS data_type,
                   NOT a.attnotnull AS nullable
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid
            WHERE n.nspname = $1
              AND c.relkind = 'm'
              AND a.attnum > 0 AND NOT a.attisdropped
              AND ($2::text IS NULL OR c.relname = $2)
              AND has_table_privilege(c.oid, 'SELECT')
            ORDER BY c.relname, a.attnum
        """
        tables: dict[str, list[dict[str, Any]]] = {}
        for r in await conn.fetch(query, schema, table):
            tables.setdefault(r["table_name"], []).append({
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["nullable"],
                "default": None,
                "max_length": None,
                "precision": None,
                "scale": None,
                "is_primary_key": False,
                "is_unique": False,
                "is_foreign_key": False,
                "foreign_table": None,
            })
        return tables

    # ------------------------------------------------------------------
    # Virtual objects
    # ------------------------------------------------------------------

    async def describe_sql(self, conn: Connection, sql: str) -> list[dict[str, Any]] | None:
        """Result columns from a prepared statement — nothing is executed."""
        try:
            stmt = await conn.prepare(sql)
        except Exception:
            return None
        return [
            {
                "name": attr.name,
                "sql_type": _PG_TYPE_NAMES.get(attr.type.name, attr.type.name),
                "nullable": True,
            }
            for attr in stmt.get_attributes()
        ]

    async def list_routines(
        self, conn: Connection, schema: str | None = None, search: str | None = None
    ) -> list[dict[str, Any]]:
        """Set-returning functions the login may execute, with input parameters.

        Only set-returning functions qualify: a Postgres PROCEDURE cannot return
        rows, and a scalar function is not a table.
        """
        query = """
            SELECT n.nspname AS schema,
                   p.proname AS name,
                   pg_get_function_identity_arguments(p.oid) AS signature,
                   pg_get_function_result(p.oid) AS returns,
                   p.pronargs AS nargs,
                   p.pronargdefaults AS nargdefaults,
                   (
                       SELECT COALESCE(json_agg(json_build_object(
                                  'name', COALESCE(p.proargnames[a.ord], ''),
                                  'sql_type', format_type(a.typ, NULL)
                              ) ORDER BY a.ord), '[]'::json)
                       FROM unnest(COALESCE(p.proallargtypes, p.proargtypes::oid[]))
                            WITH ORDINALITY AS a(typ, ord)
                       WHERE p.proargmodes IS NULL
                          OR p.proargmodes[a.ord] IN ('i', 'b', 'v')
                   )::text AS params
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE p.prokind = 'f'
              AND p.proretset
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND n.nspname NOT LIKE 'pg\\_%'
              AND has_function_privilege(p.oid, 'EXECUTE')
              AND ($1::text IS NULL OR n.nspname = $1)
              AND ($2::text IS NULL OR p.proname ILIKE '%' || $2 || '%')
            ORDER BY n.nspname, p.proname
            LIMIT 1000
        """
        import json

        routines = []
        for r in await conn.fetch(query, schema, search):
            params = json.loads(r["params"] or "[]")
            first_default = r["nargs"] - r["nargdefaults"]
            for i, prm in enumerate(params):
                prm["is_output"] = False
                prm["has_default"] = i >= first_default
            routines.append({
                "schema": r["schema"],
                "name": r["name"],
                "signature": r["signature"],
                "returns": r["returns"],
                "params": params,
            })
        return routines

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
