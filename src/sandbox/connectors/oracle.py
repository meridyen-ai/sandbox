"""
Oracle Database Connector

python-oracledb in thin mode (pure Python: no Oracle Client libraries in the
image), wrapped in a thread executor for the async BaseConnector interface.

Connection fields: ``database`` is the service name (``FREEPDB1``,
``ORCLPDB1``, ...); ``extra_params["sid"]`` connects by SID instead, for old
non-CDB servers. ``schema_name`` sets the session's current schema, so
unqualified names resolve there instead of in the user's own schema.

Values: CLOB/NCLOB columns come back as ``str`` and BLOB as ``bytes``
(``fetch_lobs=False``), never as LOB locators that would be gone once the
cursor closes. NUMBER comes back as int/float.

Read-only: a caller's query runs inside ``SET TRANSACTION READ ONLY``, which
Oracle enforces for every statement of the transaction.
"""

from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncGenerator

from sandbox.connectors.base import BaseConnector, QueryResult
from sandbox.connectors.host_policy import vet_destination
from sandbox.connectors.tls import build_ssl_context, resolve_ssl_mode
from sandbox.core.exceptions import ConnectionError, SQLExecutionError
from sandbox.core.logging import get_logger

logger = get_logger(__name__)

_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="oracle")

DEFAULT_PORT = 1521
# Owners of Oracle's own objects, left out of the catalog when no schema is set.
_SYSTEM_OWNERS = (
    "SYS", "SYSTEM", "OUTLN", "DIP", "XDB", "MDSYS", "CTXSYS", "ORDSYS", "ORDDATA",
    "OLAPSYS", "WMSYS", "LBACSYS", "DVSYS", "GSMADMIN_INTERNAL", "APPQOSSYS",
    "AUDSYS", "DBSNMP", "OJVMSYS", "REMOTE_SCHEDULER_AGENT", "DBSFWUSER",
    "GGSYS", "ANONYMOUS", "XS$NULL", "ORACLE_OCM", "SYS$UMF", "GSMCATUSER",
    "GSMUSER", "SYSBACKUP", "SYSDG", "SYSKM", "SYSRAC", "MDDATA", "DVF",
    "VECSYS", "PDBADMIN",
)
_SIMPLE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")


def oracle_identifier(name: str) -> str:
    """A schema name as Oracle stores it: an unquoted name is upper-cased
    (Oracle's own rule); a name given in double quotes is kept as written."""
    s = (name or "").strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        return s[1:-1].replace('""', '"')
    return s.upper() if _SIMPLE_NAME.match(s) else s


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _type_name(db_type: Any) -> str:
    name = getattr(db_type, "name", None) or str(db_type)
    return name[len("DB_TYPE_"):] if name.startswith("DB_TYPE_") else name


def connect_params(cfg: Any, *, host: str, ssl_mode: str, ssl_context: Any) -> dict[str, Any]:
    """Keyword arguments for ``oracledb.connect`` (thin mode)."""
    params: dict[str, Any] = {
        "user": cfg.username,
        "password": cfg.password.get_secret_value(),
        "host": host,
        "port": int(cfg.port or DEFAULT_PORT),
        "tcp_connect_timeout": float(max(1, int(cfg.connection_timeout))),
        # Retries of the TCP connect, with a pause, for a listener that is
        # briefly unavailable.
        "retry_count": 2,
        "retry_delay": 1,
        # Detect a dead peer on an idle pooled connection (minutes).
        "expire_time": 1,
    }
    sid = (cfg.extra_params or {}).get("sid")
    if sid:
        params["sid"] = str(sid)
    else:
        params["service_name"] = cfg.database
    if ssl_mode != "disable":
        params["protocol"] = "tcps"
        params["ssl_context"] = ssl_context
        # Host name check only for verify-full; the chain is verified by the
        # context for verify-ca/verify-full and not at all for require.
        params["ssl_server_dn_match"] = ssl_mode == "verify-full"
    return params


class OracleConnector(BaseConnector[Any]):
    """Oracle connector using python-oracledb (thin mode)."""

    async def connect(self) -> Any:
        cfg = self.config
        ssl_mode = resolve_ssl_mode(cfg)
        if ssl_mode in ("allow", "prefer"):
            # oracledb has no "TLS if available": TCP or TCPS, chosen up front.
            raise ConnectionError(
                f"SSL mode '{ssl_mode}' is not available for Oracle: a connection is "
                "TCP or TCPS. Use 'disable', 'require', 'verify-ca' or 'verify-full'. "
                "Not connecting.",
                connection_id=self.connection_id,
                db_type=self.db_type,
            )
        ssl_context = build_ssl_context(
            ssl_mode, cfg.ssl_ca_cert, connection_id=self.connection_id, db_type=self.db_type
        )

        # Where this may point is decided in connectors/host_policy.py. The
        # checked address is dialled unless the certificate's host name must
        # be matched (verify-full), which needs the name.
        vetted = await vet_destination(cfg)
        host = cfg.host
        if vetted.enforced and ssl_mode != "verify-full":
            host = vetted.addresses[0]

        params = connect_params(cfg, host=host, ssl_mode=ssl_mode, ssl_context=ssl_context)
        schema = oracle_identifier(cfg.schema_name) if cfg.schema_name else None
        query_timeout_ms = max(1, int(cfg.query_timeout)) * 1000

        def _connect() -> Any:
            import oracledb

            try:
                conn = oracledb.connect(**params)
            except oracledb.Error as e:
                raise ConnectionError(
                    f"Failed to connect to Oracle: {e}",
                    connection_id=cfg.id,
                    db_type="oracle",
                    cause=e,
                )
            try:
                # Driver-level timeout of every round trip: a blocked query
                # (lock wait, unresponsive host) fails instead of pinning its
                # thread forever.
                conn.call_timeout = query_timeout_ms
                if schema:
                    with conn.cursor() as cur:
                        cur.execute(f"ALTER SESSION SET CURRENT_SCHEMA = {_quote(schema)}")
            except Exception as e:
                conn.close()
                raise ConnectionError(
                    f"Connected to Oracle but could not use schema '{schema}': {e}",
                    connection_id=cfg.id,
                    db_type="oracle",
                    cause=e,
                )
            return conn

        loop = asyncio.get_running_loop()
        conn = await loop.run_in_executor(_executor, _connect)
        self._logger.debug(
            "connection_created", connection_id=self.connection_id, host=cfg.host,
            service=cfg.database, schema=schema,
        )
        return conn

    async def close_connection(self, conn: Any) -> None:
        def _close() -> None:
            try:
                conn.close()
            except Exception as e:  # noqa: BLE001 — already gone
                self._logger.warning("connection_close_error", connection_id=self.connection_id,
                                     error=str(e))

        # Fire-and-forget on the executor: safe from a coroutine being cancelled.
        _executor.submit(_close)

    @staticmethod
    def _run(cursor: Any, query: str, parameters: dict[str, Any] | None) -> None:
        q = query.strip().rstrip(";").strip()
        if parameters:
            used = set(re.findall(r":(\w+)", q))
            cursor.execute(q, {k: v for k, v in parameters.items() if k in used},
                           fetch_lobs=False)
        else:
            cursor.execute(q, fetch_lobs=False)

    @staticmethod
    def _read(cursor: Any) -> QueryResult:
        if cursor.description:
            columns = [d[0] for d in cursor.description]
            column_types = [_type_name(d[1]) for d in cursor.description]
            rows = [tuple(r) for r in cursor.fetchall()]
        else:
            columns, column_types, rows = [], [], []
        return QueryResult(
            columns=columns,
            column_types=column_types,
            rows=rows,
            row_count=len(rows),
            affected_rows=cursor.rowcount if (cursor.rowcount or 0) >= 0 and not columns else 0,
        )

    async def execute(
        self,
        conn: Any,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult:
        def _execute() -> QueryResult:
            try:
                with conn.cursor() as cursor:
                    cursor.arraysize = 1000
                    self._run(cursor, query, parameters)
                    return self._read(cursor)
            except Exception as e:
                raise SQLExecutionError(f"Query execution failed: {e}", query=query, cause=e)

        return await asyncio.get_running_loop().run_in_executor(_executor, _execute)

    async def execute_read_only(
        self,
        conn: Any,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> QueryResult:
        """The query inside a READ ONLY transaction, rolled back after."""

        def _execute() -> QueryResult:
            try:
                # SET TRANSACTION must open the transaction: end any open one.
                conn.rollback()
                with conn.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                    cursor.arraysize = 1000
                    self._run(cursor, query, parameters)
                    return self._read(cursor)
            except Exception as e:
                raise SQLExecutionError(f"Query execution failed: {e}", query=query, cause=e)
            finally:
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001 — a dead connection is replaced by the pool check
                    pass

        return await asyncio.get_running_loop().run_in_executor(_executor, _execute)

    async def execute_streaming(
        self,
        conn: Any,
        query: str,
        parameters: dict[str, Any] | None = None,
        batch_size: int = 1000,
    ) -> AsyncGenerator[list[tuple[Any, ...]], None]:
        loop = asyncio.get_running_loop()

        def _prepare() -> Any:
            cursor = conn.cursor()
            cursor.arraysize = batch_size
            self._run(cursor, query, parameters)
            return cursor

        def _fetch(cursor: Any) -> list[tuple[Any, ...]]:
            return [tuple(r) for r in cursor.fetchmany(batch_size)]

        cursor = None
        try:
            cursor = await loop.run_in_executor(_executor, _prepare)
            while True:
                batch = await loop.run_in_executor(_executor, _fetch, cursor)
                if not batch:
                    break
                yield batch
        except Exception as e:
            raise SQLExecutionError(f"Streaming query failed: {e}", query=query, cause=e)
        finally:
            if cursor is not None:
                _executor.submit(cursor.close)

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------

    def _owner_filter(self, schema: str | None) -> tuple[str, dict[str, Any]]:
        schema = schema or self.config.schema_name
        if schema:
            return "OWNER = :owner", {"owner": oracle_identifier(schema)}
        # No schema configured: the connecting user's own objects.
        return "OWNER = SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA')", {}

    async def get_tables(self, conn: Any, schema: str | None = None) -> list[str]:
        return [e["name"] for e in await self.get_table_entries(conn, schema=schema)]

    async def get_table_entries(self, conn: Any, schema: str | None = None) -> list[dict[str, Any]]:
        """Tables and views of the schema as ``[{"name", "type"}]``."""
        where, args = self._owner_filter(schema)

        def _run() -> list[dict[str, Any]]:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT TABLE_NAME, 'TABLE' FROM ALL_TABLES WHERE {where} AND NESTED = 'NO' "
                    f"AND SECONDARY = 'N' AND TABLE_NAME NOT LIKE 'BIN$%' "
                    f"UNION ALL SELECT VIEW_NAME, 'VIEW' FROM ALL_VIEWS WHERE {where} "
                    f"ORDER BY 1",
                    args,
                )
                return [{"name": r[0], "type": r[1]} for r in cur.fetchall()]

        return await asyncio.get_running_loop().run_in_executor(_executor, _run)

    async def get_columns(self, conn: Any, table: str, schema: str | None = None) -> list[dict[str, Any]]:
        where, args = self._owner_filter(schema)

        def _run() -> list[dict[str, Any]]:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COLUMN_NAME, DATA_TYPE, NULLABLE, DATA_DEFAULT, DATA_LENGTH, "
                    "DATA_SCALE FROM ALL_TAB_COLUMNS "
                    f"WHERE {where} AND TABLE_NAME = :tname ORDER BY COLUMN_ID",
                    {**args, "tname": table},
                    fetch_lobs=False,
                )
                return [_column_row(r) for r in cur.fetchall()]

        return await asyncio.get_running_loop().run_in_executor(_executor, _run)

    async def get_all_columns(self, conn: Any, schema: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """Columns of every table and view of the schema in one query."""
        where, args = self._owner_filter(schema)

        def _run() -> dict[str, list[dict[str, Any]]]:
            with conn.cursor() as cur:
                cur.arraysize = 2000
                cur.execute(
                    "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, NULLABLE, DATA_DEFAULT, "
                    "DATA_LENGTH, DATA_SCALE FROM ALL_TAB_COLUMNS "
                    f"WHERE {where} AND TABLE_NAME NOT LIKE 'BIN$%' ORDER BY TABLE_NAME, COLUMN_ID",
                    args,
                    fetch_lobs=False,
                )
                tables: dict[str, list[dict[str, Any]]] = {}
                for r in cur.fetchall():
                    tables.setdefault(r[0], []).append(_column_row(r[1:]))
                return tables

        return await asyncio.get_running_loop().run_in_executor(_executor, _run)

    async def test_connection(self, conn: Any) -> bool:
        def _test() -> bool:
            try:
                conn.ping()
                return True
            except Exception:  # noqa: BLE001
                return False

        return await asyncio.get_running_loop().run_in_executor(_executor, _test)


def _column_row(row: Any) -> dict[str, Any]:
    """(COLUMN_NAME, DATA_TYPE, NULLABLE, DATA_DEFAULT, DATA_LENGTH, DATA_SCALE)"""
    default = row[3]
    return {
        "name": row[0],
        "type": row[1],
        "nullable": row[2] == "Y",
        "default": default.strip() if isinstance(default, str) else default,
        "max_length": row[4],
        "scale": row[5],
    }
