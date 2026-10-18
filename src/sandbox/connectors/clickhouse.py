"""
ClickHouse Connector

Uses clickhouse-driver over the native protocol (port 9000, or 9440 with TLS).
A "schema" is a ClickHouse database.
"""

from __future__ import annotations

from typing import Any

from sandbox.connectors.dbapi import _NAMED_PARAM, DBAPIConnector
from sandbox.connectors.tls import VERIFYING_SSL_MODES


class ClickHouseConnector(DBAPIConnector):
    """ClickHouse."""

    label = "ClickHouse"
    driver_modules = ("clickhouse_driver",)

    def _open(self) -> Any:
        from clickhouse_driver import dbapi

        cfg = self.config
        mode = self._ssl_mode()
        if mode in ("allow", "prefer"):
            raise self._refuse(
                f"SSL mode '{mode}' is not available for ClickHouse: the native "
                "protocol is either TLS or it is not. Use 'disable' or 'require'. "
                "Not connecting."
            )
        secure = mode != "disable"
        params: dict[str, Any] = {
            "host": cfg.host,
            "port": cfg.port or (9440 if secure else 9000),
            "user": cfg.username or "default",
            "password": cfg.password.get_secret_value(),
            "database": cfg.database or "default",
            "connect_timeout": cfg.connection_timeout,
            "secure": secure,
        }
        if secure:
            # The driver checks the host name whenever it verifies, so
            # verify-ca runs as verify-full.
            params["verify"] = mode in VERIFYING_SSL_MODES
            if mode in VERIFYING_SSL_MODES:
                params["ca_certs"] = self._trust_store(mode)
        conn = dbapi.connect(**params)
        # The driver dials on first use; do it now so a bad address fails here.
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        return conn

    def _convert_parameters(
        self, query: str, parameters: dict[str, Any]
    ) -> tuple[str, Any]:
        # The driver substitutes %(name)s from a mapping, and reads every
        # other % as its own.
        return (
            _NAMED_PARAM.sub(
                lambda m: f"%({m.group(1)})s" if m.group(1) in parameters else m.group(0),
                query.replace("%", "%%"),
            ),
            parameters,
        )

    def _default_schema(self) -> str | None:
        return self.config.database or "default"

    def _entries_query(self, schema: str | None) -> tuple[str, Any]:
        return (
            "SELECT name, if(endsWith(engine, 'View'), 'VIEW', 'TABLE') "
            "FROM system.tables WHERE database = %(schema)s",
            {"schema": schema},
        )

    def _columns_query(self, schema: str | None, table: str | None) -> tuple[str, Any]:
        sql = (
            "SELECT table, name, type, "
            "if(startsWith(type, 'Nullable('), 'YES', 'NO'), default_expression "
            "FROM system.columns WHERE database = %(schema)s"
        )
        args: dict[str, Any] = {"schema": schema}
        if table is not None:
            sql += " AND table = %(table)s"
            args["table"] = table
        return sql + " ORDER BY table, position", args
