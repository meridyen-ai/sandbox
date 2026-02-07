"""Google BigQuery handler implementation."""

import json
import logging
from typing import Optional

import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

from src.data_connectors.libs.constants import DataType, HandlerType
from src.data_connectors.libs.database_handler import MetaDatabaseHandler
from src.data_connectors.libs.response import HandlerResponse, HandlerStatus

logger = logging.getLogger(__name__)


class BigQueryHandler(MetaDatabaseHandler):
    """Handler for Google BigQuery data warehouse."""

    handler_name = "bigquery"
    handler_type = HandlerType.DATA
    handler_title = "Google BigQuery"
    handler_description = "Connect to Google BigQuery data warehouse"
    handler_version = "0.1.0"
    dialect = "bigquery"

    type_mapping = {
        ("string",): DataType.VARCHAR,
        ("bytes",): DataType.BYTES,
        ("integer", "int64"): DataType.BIGINT,
        ("float", "float64"): DataType.DOUBLE,
        ("numeric", "bignumeric", "decimal"): DataType.DECIMAL,
        ("boolean", "bool"): DataType.BOOLEAN,
        ("date",): DataType.DATE,
        ("time",): DataType.TIME,
        ("datetime",): DataType.DATETIME,
        ("timestamp",): DataType.TIMESTAMP,
        ("geography",): DataType.VARCHAR,
        ("json",): DataType.JSON,
        ("array", "struct", "record"): DataType.JSON,
    }

    def __init__(self, name: str, connection_args: dict):
        super().__init__(name, connection_args)
        self._project_id = connection_args.get("project_id")
        self._dataset = connection_args.get("dataset")
        self._location = connection_args.get("location", "US")
        self._client: Optional[bigquery.Client] = None

    def connect(self) -> None:
        """Establish connection to BigQuery."""
        if self.is_connected:
            return

        try:
            credentials = None

            # Option 1: Credentials from JSON object
            if self.connection_args.get("credentials_json"):
                creds_data = self.connection_args["credentials_json"]
                if isinstance(creds_data, str):
                    creds_data = json.loads(creds_data)
                credentials = service_account.Credentials.from_service_account_info(creds_data)

            # Option 2: Credentials from file
            elif self.connection_args.get("credentials_file"):
                credentials = service_account.Credentials.from_service_account_file(
                    self.connection_args["credentials_file"]
                )

            # Option 3: Default credentials (Application Default Credentials)
            self._client = bigquery.Client(
                project=self._project_id,
                credentials=credentials,
                location=self._location,
            )
            self._connection = self._client
            self.is_connected = True
            logger.info(f"Connected to BigQuery: {self.name}")

        except Exception as e:
            self.is_connected = False
            logger.error(f"Failed to connect to BigQuery: {e}")
            raise ConnectionError(f"Failed to connect to BigQuery: {e}")

    def disconnect(self) -> None:
        """Close the BigQuery connection."""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            finally:
                self._client = None
                self._connection = None
                self.is_connected = False
                logger.info(f"Disconnected from BigQuery: {self.name}")

    def check_connection(self) -> HandlerStatus:
        """Check if the BigQuery connection is working."""
        try:
            if not self.is_connected:
                self.connect()

            # Simple test query
            query = "SELECT 1 as test"
            job = self._client.query(query)
            list(job.result())

            return HandlerStatus.success({
                "project_id": self._project_id,
                "dataset": self._dataset,
                "location": self._location,
            })

        except Exception as e:
            return HandlerStatus.error(str(e))

    def native_query(self, query: str) -> HandlerResponse:
        """Execute a raw SQL query."""
        try:
            if not self.is_connected:
                self.connect()

            job_config = bigquery.QueryJobConfig()
            if self._dataset:
                job_config.default_dataset = f"{self._project_id}.{self._dataset}"

            job = self._client.query(query, job_config=job_config)
            result = job.result()

            # Convert to DataFrame
            df = result.to_dataframe()
            return HandlerResponse.table(df)

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return HandlerResponse.error(str(e))

    def get_tables(self) -> HandlerResponse:
        """List all tables in the dataset."""
        if not self._dataset:
            return HandlerResponse.error("No dataset specified")

        query = f"""
            SELECT
                table_schema,
                table_name,
                table_type,
                creation_time,
                ddl
            FROM `{self._project_id}.{self._dataset}.INFORMATION_SCHEMA.TABLES`
            ORDER BY table_name
        """
        return self.native_query(query)

    def get_columns(self, table_name: str) -> HandlerResponse:
        """Get column information for a table."""
        if not self._dataset:
            return HandlerResponse.error("No dataset specified")

        query = f"""
            SELECT
                column_name,
                data_type,
                ordinal_position,
                is_nullable,
                is_partitioning_column
            FROM `{self._project_id}.{self._dataset}.INFORMATION_SCHEMA.COLUMNS`
            WHERE table_name = '{table_name}'
            ORDER BY ordinal_position
        """
        result = self.native_query(query)
        if result.success and result.data is not None:
            for idx, row in result.data.iterrows():
                result.data.at[idx, 'canonical_type'] = self.map_type(row['data_type']).value
        return result

    def get_primary_keys(self, table_name: str) -> HandlerResponse:
        """Get primary key columns for a table (BigQuery uses clustering)."""
        if not self._dataset:
            return HandlerResponse.error("No dataset specified")

        query = f"""
            SELECT
                table_name,
                clustering_ordinal_position,
                column_name
            FROM `{self._project_id}.{self._dataset}.INFORMATION_SCHEMA.COLUMNS`
            WHERE table_name = '{table_name}'
                AND clustering_ordinal_position IS NOT NULL
            ORDER BY clustering_ordinal_position
        """
        return self.native_query(query)

    def get_table_statistics(self, table_name: str) -> HandlerResponse:
        """Get statistics for a table."""
        if not self._dataset:
            return HandlerResponse.error("No dataset specified")

        query = f"""
            SELECT
                table_name,
                creation_time,
                last_modified_time,
                row_count,
                size_bytes,
                ROUND(size_bytes / 1024 / 1024, 2) as size_mb
            FROM `{self._project_id}.{self._dataset}.__TABLES__`
            WHERE table_id = '{table_name}'
        """
        return self.native_query(query)

    def _quote_identifier(self, identifier: str) -> str:
        """Quote a BigQuery identifier."""
        return f"`{identifier}`"
