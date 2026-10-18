"""
Google BigQuery Connector

Uses google-cloud-bigquery with a service account key. A "schema" is a
dataset; the catalog is read from the dataset's INFORMATION_SCHEMA.
"""

from __future__ import annotations

import json
from typing import Any

from sandbox.connectors.dbapi import DBAPIConnector, SimpleCursor, sql_literal


class _BigQueryCursor(SimpleCursor):
    def __init__(self, session: "_BigQuerySession") -> None:
        super().__init__()
        self._session = session

    def _run(self, sql: str) -> tuple[list[tuple[str, str]], list[tuple[Any, ...]]]:
        from google.cloud import bigquery

        session = self._session
        job_config = bigquery.QueryJobConfig()
        if session.dataset:
            job_config.default_dataset = f"{session.client.project}.{session.dataset}"
        result = session.client.query(sql, job_config=job_config).result(
            timeout=session.query_timeout
        )
        columns = [(field.name, field.field_type) for field in result.schema]
        return columns, [tuple(row.values()) for row in result]


class _BigQuerySession:
    """One client, shaped like a DB-API connection."""

    def __init__(self, client: Any, dataset: str | None, query_timeout: int) -> None:
        self.client = client
        self.dataset = dataset
        self.query_timeout = query_timeout

    def cursor(self) -> _BigQueryCursor:
        return _BigQueryCursor(self)

    def close(self) -> None:
        self.client.close()


class BigQueryConnector(DBAPIConnector):
    """Google BigQuery."""

    label = "Google BigQuery"
    driver_modules = ("google.cloud.bigquery",)

    def _host(self) -> str:
        return "bigquery.googleapis.com"

    def _open(self) -> Any:
        from google.cloud import bigquery
        from google.oauth2 import service_account

        cfg = self.config
        key = self._require(
            self._param("credentials_json") or cfg.password.get_secret_value(),
            "service account",
        )
        try:
            info = json.loads(key) if isinstance(key, str) else dict(key)
        except (TypeError, ValueError):
            raise self._refuse(
                "The BigQuery service account must be the key file's JSON. Not connecting."
            ) from None
        credentials = service_account.Credentials.from_service_account_info(info)
        client = bigquery.Client(
            project=self._param("project_id") or cfg.database or info.get("project_id"),
            credentials=credentials,
            location=self._param("location"),
        )
        session = _BigQuerySession(client, self._schema(None), cfg.query_timeout)
        # Building a client contacts nothing; a query is what proves the key.
        session.cursor().execute("SELECT 1")
        return session

    def _default_schema(self) -> str | None:
        return self._param("dataset")

    def _information_schema(self, schema: str | None, view: str) -> str:
        dataset = self._require(schema, "dataset")
        return "`" + str(dataset).replace("`", "") + "`.INFORMATION_SCHEMA." + view

    def _entries_query(self, schema: str | None) -> tuple[str, tuple[Any, ...]]:
        return (
            f"SELECT table_name, table_type FROM {self._information_schema(schema, 'TABLES')}",
            (),
        )

    def _columns_query(
        self, schema: str | None, table: str | None
    ) -> tuple[str, tuple[Any, ...]]:
        sql = (
            "SELECT table_name, column_name, data_type, is_nullable, NULL "
            f"FROM {self._information_schema(schema, 'COLUMNS')}"
        )
        if table is not None:
            sql += f" WHERE table_name = {sql_literal(table)}"
        return sql + " ORDER BY table_name, ordinal_position", ()
