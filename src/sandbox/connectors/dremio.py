"""
Dremio Connector

Reached through Dremio's REST API (the port its web UI is served on): a query
is submitted as a job, polled until it finishes, and its result read page by
page. A "schema" is the dotted path of a space, source or folder.

With a user name the password is the user's password; without one it is a
personal access token.
"""

from __future__ import annotations

import time
from typing import Any

from sandbox.connectors.dbapi import DBAPIConnector, SimpleCursor, sql_literal

_PAGE = 500


class _DremioCursor(SimpleCursor):
    def __init__(self, session: "_DremioSession") -> None:
        super().__init__()
        self._session = session

    def _run(self, sql: str) -> tuple[list[tuple[str, str]], list[tuple[Any, ...]]]:
        session = self._session
        body: dict[str, Any] = {"sql": sql}
        if session.context:
            body["context"] = session.context
        job_id = session.call("POST", "/api/v3/sql", json=body)["id"]

        deadline = time.monotonic() + session.query_timeout
        delay = 0.2
        while True:
            job = session.call("GET", f"/api/v3/job/{job_id}")
            state = job.get("jobState")
            if state == "COMPLETED":
                break
            if state in ("FAILED", "CANCELED", "CANCELLED"):
                raise RuntimeError(job.get("errorMessage") or f"Query {state}")
            if time.monotonic() > deadline:
                session.call("POST", f"/api/v3/job/{job_id}/cancel")
                raise RuntimeError(f"Query did not finish in {session.query_timeout}s")
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)

        columns: list[tuple[str, str]] = []
        rows: list[tuple[Any, ...]] = []
        total = int(job.get("rowCount") or 0)
        while True:
            page = session.call(
                "GET", f"/api/v3/job/{job_id}/results?offset={len(rows)}&limit={_PAGE}"
            )
            if not columns:
                columns = [
                    (field["name"], (field.get("type") or {}).get("name", ""))
                    for field in page.get("schema", [])
                ]
            batch = page.get("rows", [])
            rows.extend(tuple(record.get(name) for name, _ in columns) for record in batch)
            if not batch or len(rows) >= max(total, int(page.get("rowCount") or 0)):
                break
        return columns, rows


class _DremioSession:
    """One authenticated HTTP session, shaped like a DB-API connection."""

    def __init__(
        self,
        http: Any,
        base_url: str,
        context: list[str],
        timeout: int,
        query_timeout: int,
    ) -> None:
        self.http = http
        self.base_url = base_url
        self.context = context
        self.timeout = timeout
        self.query_timeout = query_timeout

    def call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.http.request(
            method, self.base_url + path, timeout=self.timeout, **kwargs
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("errorMessage") or response.text
            except ValueError:
                detail = response.text
            raise RuntimeError(f"Dremio answered {response.status_code}: {detail[:500]}")
        return response.json() if response.content else {}

    def cursor(self) -> _DremioCursor:
        return _DremioCursor(self)

    def close(self) -> None:
        self.http.close()


class DremioConnector(DBAPIConnector):
    """Dremio Software and Dremio Cloud."""

    label = "Dremio"
    driver_modules = ("requests",)

    def _scheme(self) -> tuple[str, bool | str]:
        cfg = self.config
        if cfg.ssl_mode or cfg.ssl_enabled:
            return self._http_tls()
        if self._param("ssl") in (True, "true", "True", 1) or cfg.port == 443:
            return "https", self._ca_file() or True
        return "http", False

    def _open(self) -> Any:
        import requests

        cfg = self.config
        scheme, verify = self._scheme()
        base_url = f"{scheme}://{cfg.host}:{cfg.port or (443 if scheme == 'https' else 9047)}"
        http = requests.Session()
        http.verify = verify
        # The host was checked before dialling; a redirect could point anywhere.
        http.max_redirects = 0
        secret = cfg.password.get_secret_value()
        if cfg.username:
            response = http.post(
                f"{base_url}/apiv2/login",
                json={"userName": cfg.username, "password": secret},
                timeout=cfg.connection_timeout,
                allow_redirects=False,
            )
            if response.status_code != 200:
                raise self._refuse(
                    f"Dremio refused the sign-in ({response.status_code}). Not connecting."
                )
            http.headers["Authorization"] = "_dremio" + response.json()["token"]
        else:
            http.headers["Authorization"] = f"Bearer {secret}"
        schema = self._schema(None)
        return _DremioSession(
            http,
            base_url,
            _path(schema) if schema else [],
            cfg.connection_timeout,
            cfg.query_timeout,
        )

    def _entries_query(self, schema: str | None) -> tuple[str, tuple[Any, ...]]:
        schema = self._require(schema, "schema")
        return (
            'SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA."TABLES" '
            f"WHERE TABLE_SCHEMA = {sql_literal(schema)}",
            (),
        )

    def _columns_query(
        self, schema: str | None, table: str | None
    ) -> tuple[str, tuple[Any, ...]]:
        schema = self._require(schema, "schema")
        sql = (
            "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT "
            f'FROM INFORMATION_SCHEMA."COLUMNS" WHERE TABLE_SCHEMA = {sql_literal(schema)}'
        )
        if table is not None:
            sql += f" AND TABLE_NAME = {sql_literal(table)}"
        return sql + " ORDER BY TABLE_NAME, ORDINAL_POSITION", ()


def _path(schema: str) -> list[str]:
    """A dotted schema path as Dremio's context list. A part that itself
    contains a dot is written in double quotes."""
    parts: list[str] = []
    current = ""
    quoted = False
    for char in schema:
        if char == '"':
            quoted = not quoted
        elif char == "." and not quoted:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return [p for p in parts if p]
