"""Trino handler implementation."""

import logging
from typing import Optional

import pandas as pd
import trino

from src.data_connectors.libs.constants import DataType, HandlerType
from src.data_connectors.libs.database_handler import MetaDatabaseHandler
from src.data_connectors.libs.response import HandlerResponse, HandlerStatus

logger = logging.getLogger(__name__)


class TrinoHandler(MetaDatabaseHandler):
    """Handler for Trino (and Presto) query engines."""

    handler_name = "trino"
    handler_type = HandlerType.DATA
    handler_title = "Trino"
    handler_description = "Connect to Trino query engine"
    handler_version = "0.1.0"
    dialect = "trino"

    type_mapping = {
        ("tinyint",): DataType.SMALLINT,
        ("smallint",): DataType.SMALLINT,
        ("integer", "int"): DataType.INTEGER,
        ("bigint",): DataType.BIGINT,
        ("real",): DataType.FLOAT,
        ("double",): DataType.DOUBLE,
        ("decimal",): DataType.DECIMAL,
        ("varchar", "char"): DataType.VARCHAR,
        ("varbinary",): DataType.BYTES,
        ("boolean",): DataType.BOOLEAN,
        ("date",): DataType.DATE,
        ("time", "time with time zone"): DataType.TIME,
        ("timestamp", "timestamp with time zone"): DataType.TIMESTAMP,
        ("json",): DataType.JSON,
        ("array",): DataType.ARRAY,
        ("map", "row"): DataType.JSON,
        ("uuid",): DataType.VARCHAR,
        ("ipaddress",): DataType.VARCHAR,
    }

    def __init__(self, name: str, connection_args: dict):
        super().__init__(name, connection_args)
        self._catalog = connection_args.get("catalog")
        self._schema = connection_args.get("schema")

    def connect(self) -> None:
        """Establish connection to Trino."""
        if self.is_connected:
            return

        try:
            conn_params = {
                "host": self.connection_args["host"],
                "port": self.connection_args.get("port", 8080),
                "user": self.connection_args["user"],
                "catalog": self._catalog,
                "http_scheme": self.connection_args.get("http_scheme", "http"),
            }

            if self._schema:
                conn_params["schema"] = self._schema

            if self.connection_args.get("password"):
                conn_params["auth"] = trino.auth.BasicAuthentication(
                    self.connection_args["user"],
                    self.connection_args["password"]
                )

            self._connection = trino.dbapi.connect(**conn_params)
            self.is_connected = True
            logger.info(f"Connected to Trino: {self.name}")

        except Exception as e:
            self.is_connected = False
            logger.error(f"Failed to connect to Trino: {e}")
            raise ConnectionError(f"Failed to connect to Trino: {e}")

    def disconnect(self) -> None:
        """Close the Trino connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            finally:
                self._connection = None
                self.is_connected = False
                logger.info(f"Disconnected from Trino: {self.name}")

    def check_connection(self) -> HandlerStatus:
        """Check if the Trino connection is working."""
        try:
            if not self.is_connected:
                self.connect()

            cursor = self._connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchall()
            cursor.close()

            return HandlerStatus.success({
                "catalog": self._catalog,
                "schema": self._schema,
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
        schema_filter = f"AND table_schema = '{self._schema}'" if self._schema else ""
        query = f"""
            SELECT
                table_schema,
                table_name,
                table_type
            FROM {self._catalog}.information_schema.tables
            WHERE table_catalog = '{self._catalog}'
                {schema_filter}
            ORDER BY table_schema, table_name
        """
        return self.native_query(query)

    def get_columns(self, table_name: str) -> HandlerResponse:
        """Get column information for a table."""
        schema_filter = f"AND table_schema = '{self._schema}'" if self._schema else ""
        query = f"""
            SELECT
                column_name,
                data_type,
                ordinal_position,
                column_default,
                is_nullable
            FROM {self._catalog}.information_schema.columns
            WHERE table_catalog = '{self._catalog}'
                AND table_name = '{table_name}'
                {schema_filter}
            ORDER BY ordinal_position
        """
        result = self.native_query(query)
        if result.success and result.data is not None:
            for idx, row in result.data.iterrows():
                result.data.at[idx, 'canonical_type'] = self.map_type(row['data_type']).value
        return result

    def _quote_identifier(self, identifier: str) -> str:
        """Quote a Trino identifier."""
        return f'"{identifier}"'
