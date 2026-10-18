"""
Databricks Connector

Uses databricks-sql-connector against a SQL warehouse or cluster. The catalog
is read through the driver's metadata calls, which answer for Unity Catalog
and the Hive metastore alike.
"""

from __future__ import annotations

from typing import Any

from sandbox.connectors.dbapi import DBAPIConnector, _close_quietly, _column_row, _kind, _run


class DatabricksConnector(DBAPIConnector):
    """Databricks SQL."""

    label = "Databricks"
    driver_modules = ("databricks.sql",)

    def _server(self) -> str:
        host = str(self._require(self.config.host, "host")).strip()
        return host.split("://", 1)[-1].split("/", 1)[0]

    def _host(self) -> str:
        return self._server()

    def _catalog(self) -> str | None:
        return self._param("catalog") or self.config.database or None

    def _open(self) -> Any:
        from databricks import sql

        cfg = self.config
        params: dict[str, Any] = {
            "server_hostname": self._server(),
            "http_path": self._require(self._param("http_path"), "HTTP path"),
            "access_token": self._access_token(),
            # Left alone the driver retries an unreachable workspace for minutes.
            "_socket_timeout": cfg.connection_timeout,
            "_retry_stop_after_attempts_count": 2,
            "_retry_stop_after_attempts_duration": cfg.connection_timeout,
        }
        if self._catalog():
            params["catalog"] = self._catalog()
        if self._schema(None):
            params["schema"] = self._schema(None)
        return sql.connect(**params)

    def _access_token(self) -> str:
        secret = self.config.password.get_secret_value()
        if str(self._param("auth_type", "personal_access_token")) != "service_account":
            return self._require(self._param("access_token") or secret, "access token")
        # A service principal exchanges its client secret for a workspace token.
        import requests

        response = requests.post(
            f"https://{self._server()}/oidc/v1/token",
            auth=(
                self._require(self._param("client_id") or self.config.username, "client ID"),
                self._require(self._param("client_secret") or secret, "client secret"),
            ),
            data={"grant_type": "client_credentials", "scope": "all-apis"},
            timeout=self.config.connection_timeout,
        )
        if response.status_code != 200:
            raise self._refuse(
                f"Databricks refused the service principal ({response.status_code}). "
                "Not connecting."
            )
        return response.json()["access_token"]

    def _convert_parameters(
        self, query: str, parameters: dict[str, Any]
    ) -> tuple[str, Any]:
        # :name is the driver's own parameter syntax.
        return query, parameters

    def _default_schema(self) -> str | None:
        return "default"

    def _metadata(self, conn: Any, call: str, **filters: Any) -> list[dict[str, Any]]:
        cursor = conn.cursor()
        try:
            getattr(cursor, call)(**{k: v for k, v in filters.items() if v})
            names = [str(d[0]).upper() for d in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]
        finally:
            _close_quietly(cursor)

    async def get_table_entries(
        self, conn: Any, schema: str | None = None
    ) -> list[dict[str, Any]]:
        rows = await _run(
            lambda: self._metadata(
                conn, "tables", catalog_name=self._catalog(), schema_name=self._schema(schema)
            )
        )
        entries = {
            r["TABLE_NAME"]: {"name": r["TABLE_NAME"], "type": _kind(r.get("TABLE_TYPE"))}
            for r in rows
        }
        return sorted(entries.values(), key=lambda e: str(e["name"]).lower())

    async def get_all_columns(
        self, conn: Any, schema: str | None = None, table: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        rows = await _run(
            lambda: self._metadata(
                conn,
                "columns",
                catalog_name=self._catalog(),
                schema_name=self._schema(schema),
                table_name=table,
            )
        )
        rows.sort(key=lambda r: (str(r["TABLE_NAME"]), r.get("ORDINAL_POSITION") or 0))
        tables: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            tables.setdefault(r["TABLE_NAME"], []).append(
                _column_row(
                    (
                        r["COLUMN_NAME"],
                        r.get("TYPE_NAME"),
                        r.get("IS_NULLABLE", r.get("NULLABLE", 1)),
                        r.get("COLUMN_DEF"),
                        r.get("COLUMN_SIZE"),
                        None,
                        r.get("DECIMAL_DIGITS"),
                    )
                )
            )
        return tables

    async def get_columns(
        self, conn: Any, table: str, schema: str | None = None
    ) -> list[dict[str, Any]]:
        tables = await self.get_all_columns(conn, schema=schema, table=table)
        return tables.get(table) or next(iter(tables.values()), [])
