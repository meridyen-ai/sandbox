"""
Amazon Redshift Connector

Redshift speaks the PostgreSQL wire protocol but not the parts of it asyncpg
relies on (server-side type introspection), so it is reached with psycopg2.
"""

from __future__ import annotations

from typing import Any

from sandbox.connectors.dbapi import DBAPIConnector, InformationSchemaMixin
from sandbox.connectors.tls import VERIFYING_SSL_MODES


class LibpqConnector(DBAPIConnector):
    """A server reached through libpq (psycopg2) with PostgreSQL's SSL modes."""

    driver_modules = ("psycopg2",)
    placeholder = "%s"
    default_port = 5432
    # The mode of a connection that states none: libpq's own default.
    default_ssl_mode = "prefer"

    def _open(self) -> Any:
        import psycopg2

        cfg = self.config
        mode = self._ssl_mode() if (cfg.ssl_mode or cfg.ssl_enabled) else self.default_ssl_mode
        params: dict[str, Any] = {
            "host": cfg.host,
            "port": cfg.port or self.default_port,
            "dbname": cfg.database,
            "user": cfg.username,
            "password": cfg.password.get_secret_value(),
            "connect_timeout": cfg.connection_timeout,
            "sslmode": mode,
        }
        if mode in VERIFYING_SSL_MODES:
            params["sslrootcert"] = self._trust_store(mode)
        conn = psycopg2.connect(**params)
        # Each statement stands alone; nothing is left open in a transaction.
        conn.autocommit = True
        return conn


class RedshiftConnector(InformationSchemaMixin, LibpqConnector):
    """Amazon Redshift (provisioned clusters and Serverless workgroups)."""

    label = "Amazon Redshift"
    default_port = 5439

    def _default_schema(self) -> str | None:
        return "public"
