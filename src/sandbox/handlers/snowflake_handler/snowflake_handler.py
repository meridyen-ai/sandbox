"""Snowflake data warehouse handler implementation."""

import logging
from typing import Optional

import pandas as pd
import snowflake.connector
from snowflake.connector import DictCursor

from src.data_connectors.libs.constants import DataType, HandlerType
from src.data_connectors.libs.database_handler import MetaDatabaseHandler
from src.data_connectors.libs.response import HandlerResponse, HandlerStatus

logger = logging.getLogger(__name__)


class SnowflakeHandler(MetaDatabaseHandler):
    """Handler for Snowflake data warehouse."""

    handler_name = "snowflake"
    handler_type = HandlerType.DATA
    handler_title = "Snowflake"
    handler_description = "Connect to Snowflake data warehouse"
    handler_version = "0.1.0"
    dialect = "snowflake"

    type_mapping = {
        ("number", "decimal", "numeric"): DataType.DECIMAL,
        ("int", "integer", "bigint", "smallint", "tinyint", "byteint"): DataType.INTEGER,
        ("float", "float4", "float8", "double", "double precision", "real"): DataType.DOUBLE,
        ("varchar", "char", "character", "string", "text"): DataType.VARCHAR,
        ("binary", "varbinary"): DataType.BYTES,
        ("boolean",): DataType.BOOLEAN,
        ("date",): DataType.DATE,
        ("time",): DataType.TIME,
        ("datetime", "timestamp", "timestamp_ltz", "timestamp_ntz", "timestamp_tz"): DataType.TIMESTAMP,
        ("variant", "object", "array"): DataType.JSON,
    }

    def __init__(self, name: str, connection_args: dict):
        super().__init__(name, connection_args)
        self._database = connection_args.get("database")
        self._schema = connection_args.get("schema", "PUBLIC")
        self._warehouse = connection_args.get("warehouse")

    def connect(self) -> None:
        """Establish connection to Snowflake."""
        if self.is_connected:
            return

        try:
            conn_params = {
                "account": self.connection_args["account"],
                "user": self.connection_args["user"],
                "password": self.connection_args["password"],
                "database": self.connection_args["database"],
                "warehouse": self.connection_args["warehouse"],
                "schema": self.connection_args.get("schema", "PUBLIC"),
            }

            if self.connection_args.get("role"):
                conn_params["role"] = self.connection_args["role"]

            self._connection = snowflake.connector.connect(**conn_params)
            self.is_connected = True
            logger.info(f"Connected to Snowflake: {self.name}")

        except Exception as e:
            self.is_connected = False
            logger.error(f"Failed to connect to Snowflake: {e}")
            raise ConnectionError(f"Failed to connect to Snowflake: {e}")

    def disconnect(self) -> None:
        """Close the Snowflake connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            finally:
                self._connection = None
                self.is_connected = False
                logger.info(f"Disconnected from Snowflake: {self.name}")

    def check_connection(self) -> HandlerStatus:
        """Check if the Snowflake connection is working."""
        try:
            if not self.is_connected:
                self.connect()

            cursor = self._connection.cursor()
            cursor.execute("SELECT CURRENT_VERSION(), CURRENT_ACCOUNT(), CURRENT_DATABASE()")
            row = cursor.fetchone()
            cursor.close()

            return HandlerStatus.success({
                "version": row[0],
                "account": row[1],
                "database": row[2],
                "warehouse": self._warehouse,
                "schema": self._schema,
            })

        except Exception as e:
            return HandlerStatus.error(str(e))

    def native_query(self, query: str) -> HandlerResponse:
        """Execute a raw SQL query."""
        try:
            if not self.is_connected:
                self.connect()

            cursor = self._connection.cursor(DictCursor)
            cursor.execute(query)

            if cursor.description:
                rows = cursor.fetchall()
                df = pd.DataFrame(rows)
                cursor.close()
                return HandlerResponse.table(df)
            else:
                affected = cursor.rowcount
                cursor.close()
                return HandlerResponse.ok(affected_rows=affected)

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return HandlerResponse.error(str(e))

    def get_tables(self) -> HandlerResponse:
        """List all tables in the current schema."""
        query = f"""
            SELECT
                TABLE_SCHEMA AS table_schema,
                TABLE_NAME AS table_name,
                TABLE_TYPE AS table_type
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = '{self._schema}'
            ORDER BY TABLE_NAME
        """
        return self.native_query(query)

    def get_columns(self, table_name: str) -> HandlerResponse:
        """Get column information for a table."""
        query = f"""
            SELECT
                COLUMN_NAME AS column_name,
                DATA_TYPE AS data_type,
                ORDINAL_POSITION AS ordinal_position,
                COLUMN_DEFAULT AS column_default,
                IS_NULLABLE AS is_nullable,
                CHARACTER_MAXIMUM_LENGTH AS max_length,
                NUMERIC_PRECISION AS numeric_precision,
                NUMERIC_SCALE AS numeric_scale,
                COMMENT AS description
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = '{self._schema}'
                AND TABLE_NAME = '{table_name}'
            ORDER BY ORDINAL_POSITION
        """
        result = self.native_query(query)
        if result.success and result.data is not None:
            for idx, row in result.data.iterrows():
                result.data.at[idx, 'canonical_type'] = self.map_type(row['data_type']).value
        return result

    def _quote_identifier(self, identifier: str) -> str:
        """Quote a Snowflake identifier."""
        return f'"{identifier}"'
