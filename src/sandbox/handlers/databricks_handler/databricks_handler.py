"""Databricks handler implementation."""

import logging
from typing import Optional

import pandas as pd
from databricks import sql as databricks_sql

from src.data_connectors.libs.constants import DataType, HandlerType
from src.data_connectors.libs.database_handler import MetaDatabaseHandler
from src.data_connectors.libs.response import HandlerResponse, HandlerStatus

logger = logging.getLogger(__name__)


class DatabricksHandler(MetaDatabaseHandler):
    """Handler for Databricks SQL warehouses and clusters."""

    handler_name = "databricks"
    handler_type = HandlerType.DATA
    handler_title = "Databricks"
    handler_description = "Connect to Databricks SQL warehouses and clusters"
    handler_version = "0.1.0"
    dialect = "databricks"

    type_mapping = {
        ("tinyint", "smallint"): DataType.SMALLINT,
        ("int", "integer"): DataType.INTEGER,
        ("bigint", "long"): DataType.BIGINT,
        ("float", "real"): DataType.FLOAT,
        ("double",): DataType.DOUBLE,
        ("decimal", "numeric"): DataType.DECIMAL,
        ("string", "varchar", "char"): DataType.VARCHAR,
        ("binary",): DataType.BYTES,
        ("boolean",): DataType.BOOLEAN,
        ("date",): DataType.DATE,
        ("timestamp", "timestamp_ntz"): DataType.TIMESTAMP,
        ("array",): DataType.ARRAY,
        ("map", "struct"): DataType.JSON,
    }

    def __init__(self, name: str, connection_args: dict):
        super().__init__(name, connection_args)
        self._catalog = connection_args.get("catalog", "hive_metastore")
        self._schema = connection_args.get("schema", "default")
        self._auth_type = connection_args.get("auth_type", "personal_access_token")

    def connect(self) -> None:
        """Establish connection to Databricks."""
        if self.is_connected:
            return

        try:
            if self._auth_type == "service_account":
                self._connect_service_account()
            else:
                self._connect_personal_access_token()

            self.is_connected = True
            logger.info(f"Connected to Databricks: {self.name}")

        except Exception as e:
            self.is_connected = False
            logger.error(f"Failed to connect to Databricks: {e}")
            raise ConnectionError(f"Failed to connect to Databricks: {e}")

    def _connect_personal_access_token(self) -> None:
        """Connect using Personal Access Token."""
        self._connection = databricks_sql.connect(
            server_hostname=self.connection_args["host"],
            http_path=self.connection_args["http_path"],
            access_token=self.connection_args["access_token"],
            catalog=self._catalog,
            schema=self._schema,
        )

    def _connect_service_account(self) -> None:
        """Connect using Service Account (OAuth M2M)."""
        from databricks.sdk.core import oauth_service_principal

        def credential_provider():
            return oauth_service_principal(
                self.connection_args["host"],
                self.connection_args["client_id"],
                self.connection_args["client_secret"],
            )

        self._connection = databricks_sql.connect(
            server_hostname=self.connection_args["host"],
            http_path=self.connection_args["http_path"],
            credentials_provider=credential_provider,
            catalog=self._catalog,
            schema=self._schema,
        )

    def disconnect(self) -> None:
        """Close the Databricks connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            finally:
                self._connection = None
                self.is_connected = False
                logger.info(f"Disconnected from Databricks: {self.name}")

    def check_connection(self) -> HandlerStatus:
        """Check if the Databricks connection is working."""
        try:
            if not self.is_connected:
                self.connect()

            cursor = self._connection.cursor()
            cursor.execute("SELECT current_catalog(), current_schema()")
            row = cursor.fetchone()
            cursor.close()

            return HandlerStatus.success({
                "catalog": row[0] if row else self._catalog,
                "schema": row[1] if row else self._schema,
            })

        except Exception as e:
            return HandlerStatus.error(str(e))

    def native_query(self, query: str) -> HandlerResponse:
        """Execute a raw SQL query."""
        try:
            if not self.is_connected:
                self.connect()

            cursor = self._connection.cursor()
            cursor.execute(query)

            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                data = [dict(zip(columns, row)) for row in rows]
                df = pd.DataFrame(data)
                cursor.close()
                return HandlerResponse.table(df)
            else:
                cursor.close()
                return HandlerResponse.ok()

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return HandlerResponse.error(str(e))

    def get_tables(self) -> HandlerResponse:
        """List all tables in the current catalog/schema."""
        query = f"""
            SHOW TABLES IN {self._catalog}.{self._schema}
        """
        result = self.native_query(query)

        # Transform SHOW TABLES output to standard format
        if result.success and result.data is not None and not result.data.empty:
            df = pd.DataFrame({
                'table_schema': self._schema,
                'table_name': result.data['tableName'] if 'tableName' in result.data.columns else result.data.iloc[:, 1],
                'table_type': 'BASE TABLE',
            })
            return HandlerResponse.table(df)
        return result

    def get_columns(self, table_name: str) -> HandlerResponse:
        """Get column information for a table."""
        query = f"DESCRIBE TABLE {self._catalog}.{self._schema}.{table_name}"
        result = self.native_query(query)

        if result.success and result.data is not None:
            # Databricks DESCRIBE returns col_name, data_type, comment
            df = result.data.copy()
            if 'col_name' in df.columns:
                df = df.rename(columns={
                    'col_name': 'column_name',
                    'data_type': 'data_type',
                    'comment': 'description',
                })
                df['ordinal_position'] = range(1, len(df) + 1)

                # Filter out partition info rows
                df = df[~df['column_name'].str.startswith('#')]

                # Add canonical types
                for idx, row in df.iterrows():
                    df.at[idx, 'canonical_type'] = self.map_type(row['data_type']).value

            return HandlerResponse.table(df)
        return result

    def get_table_statistics(self, table_name: str) -> HandlerResponse:
        """Get statistics for a table."""
        query = f"DESCRIBE DETAIL {self._catalog}.{self._schema}.{table_name}"
        return self.native_query(query)

    def _quote_identifier(self, identifier: str) -> str:
        """Quote a Databricks identifier."""
        return f"`{identifier}`"
