"""
Amazon Athena Connector

Athena has no wire protocol: a query is started through the AWS API, polled
until it finishes, and its result read page by page. The access key is the
connection's user name and the secret key its password.
"""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from sandbox.connectors.dbapi import DBAPIConnector, SimpleCursor, sql_literal

_INTEGERS = {"tinyint", "smallint", "integer", "int", "bigint"}
_FLOATS = {"float", "double", "real"}


def _value(text: str | None, type_name: str) -> Any:
    """Athena returns every value as text."""
    if text is None:
        return None
    try:
        if type_name in _INTEGERS:
            return int(text)
        if type_name in _FLOATS:
            return float(text)
        if type_name == "decimal":
            return Decimal(text)
        if type_name == "boolean":
            return text.lower() == "true"
    except (ValueError, ArithmeticError):
        pass
    return text


class _AthenaCursor(SimpleCursor):
    def __init__(self, session: "_AthenaSession") -> None:
        super().__init__()
        self._session = session

    def _run(self, sql: str) -> tuple[list[tuple[str, str]], list[tuple[Any, ...]]]:
        session = self._session
        client = session.client
        query_id = client.start_query_execution(QueryString=sql, **session.request)[
            "QueryExecutionId"
        ]
        deadline = time.monotonic() + session.query_timeout
        delay = 0.2
        while True:
            execution = client.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
            state = execution["Status"]["State"]
            if state == "SUCCEEDED":
                break
            if state in ("FAILED", "CANCELLED"):
                raise RuntimeError(execution["Status"].get("StateChangeReason") or f"Query {state}")
            if time.monotonic() > deadline:
                client.stop_query_execution(QueryExecutionId=query_id)
                raise RuntimeError(f"Query did not finish in {session.query_timeout}s")
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)

        columns: list[tuple[str, str]] = []
        rows: list[tuple[Any, ...]] = []
        pages = client.get_paginator("get_query_results").paginate(QueryExecutionId=query_id)
        for index, page in enumerate(pages):
            result = page["ResultSet"]
            if index == 0:
                columns = [
                    (info["Name"], info["Type"])
                    for info in result["ResultSetMetadata"]["ColumnInfo"]
                ]
            for data in result["Rows"]:
                rows.append(
                    tuple(
                        _value(cell.get("VarCharValue"), columns[i][1])
                        for i, cell in enumerate(data["Data"])
                    )
                )
        # A SELECT's first row repeats the column names.
        if (
            execution.get("StatementType") == "DML"
            and rows
            and list(rows[0]) == [name for name, _ in columns]
        ):
            rows = rows[1:]
        return columns, rows


class _AthenaSession:
    """One Athena client, shaped like a DB-API connection."""

    def __init__(self, client: Any, request: dict[str, Any], query_timeout: int) -> None:
        self.client = client
        self.request = request
        self.query_timeout = query_timeout

    def cursor(self) -> _AthenaCursor:
        return _AthenaCursor(self)

    def close(self) -> None:
        self.client.close()


class AthenaConnector(DBAPIConnector):
    """Amazon Athena."""

    label = "Amazon Athena"
    driver_modules = ("boto3",)

    def _region(self) -> str:
        return str(self._require(self._param("region_name"), "region"))

    def _host(self) -> str:
        endpoint = self._param("endpoint_vpc")
        if endpoint:
            return urlparse(endpoint if "://" in endpoint else f"https://{endpoint}").hostname or ""
        return f"athena.{self._region()}.amazonaws.com"

    def _open(self) -> Any:
        import boto3
        from botocore.config import Config

        cfg = self.config
        endpoint = self._param("endpoint_vpc")
        client = boto3.client(
            "athena",
            region_name=self._region(),
            aws_access_key_id=self._require(
                self._param("aws_access_key_id") or cfg.username, "access key"
            ),
            aws_secret_access_key=self._require(
                self._param("aws_secret_access_key") or cfg.password.get_secret_value(),
                "secret key",
            ),
            endpoint_url=(endpoint if "://" in endpoint else f"https://{endpoint}") if endpoint else None,
            config=Config(connect_timeout=cfg.connection_timeout, retries={"max_attempts": 3}),
        )
        request: dict[str, Any] = {
            "QueryExecutionContext": {
                "Database": self._schema(None),
                "Catalog": self._param("catalog", "AwsDataCatalog"),
            }
        }
        output = self._param("results_output_location")
        if output:
            request["ResultConfiguration"] = {"OutputLocation": output}
        workgroup = self._param("workgroup")
        if workgroup:
            request["WorkGroup"] = workgroup
        session = _AthenaSession(client, request, cfg.query_timeout)
        # Building a client contacts nothing; a query is what proves the keys,
        # the workgroup and the output location.
        session.cursor().execute("SELECT 1")
        return session

    def _default_schema(self) -> str | None:
        return self.config.database or "default"

    def _entries_query(self, schema: str | None) -> tuple[str, tuple[Any, ...]]:
        return (
            "SELECT table_name, table_type FROM information_schema.tables "
            f"WHERE table_schema = {sql_literal(schema)}",
            (),
        )

    def _columns_query(
        self, schema: str | None, table: str | None
    ) -> tuple[str, tuple[Any, ...]]:
        sql = (
            "SELECT table_name, column_name, data_type, is_nullable, column_default "
            f"FROM information_schema.columns WHERE table_schema = {sql_literal(schema)}"
        )
        if table is not None:
            sql += f" AND table_name = {sql_literal(table)}"
        return sql + " ORDER BY table_name, ordinal_position", ()
