"""Amazon Athena handler implementation."""

import logging
from typing import Optional

import pandas as pd
from pyathena import connect as athena_connect
from pyathena.cursor import DictCursor

from src.data_connectors.libs.constants import DataType, HandlerType
from src.data_connectors.libs.database_handler import MetaDatabaseHandler
from src.data_connectors.libs.response import HandlerResponse, HandlerStatus

logger = logging.getLogger(__name__)


class AthenaHandler(MetaDatabaseHandler):
    """Handler for Amazon Athena serverless query service."""

    handler_name = "athena"
    handler_type = HandlerType.DATA
    handler_title = "Amazon Athena"
    handler_description = "Connect to Amazon Athena"
    handler_version = "0.1.0"
    dialect = "athena"

    type_mapping = {
        ("tinyint",): DataType.SMALLINT,
        ("smallint",): DataType.SMALLINT,
        ("int", "integer"): DataType.INTEGER,
        ("bigint",): DataType.BIGINT,
        ("float", "real"): DataType.FLOAT,
        ("double",): DataType.DOUBLE,
        ("decimal",): DataType.DECIMAL,
        ("char",): DataType.CHAR,
        ("varchar", "string"): DataType.VARCHAR,
        ("binary", "varbinary"): DataType.BYTES,
        ("boolean",): DataType.BOOLEAN,
        ("date",): DataType.DATE,
        ("timestamp",): DataType.TIMESTAMP,
        ("array",): DataType.ARRAY,
        ("map", "struct", "row"): DataType.JSON,
    }

    def __init__(self, name: str, connection_args: dict):
        super().__init__(name, connection_args)
        self._database = connection_args.get("database", "default")
        self._workgroup = connection_args.get("workgroup", "primary")

    def connect(self) -> None:
        """Establish connection to Athena."""
        if self.is_connected:
            return

        try:
            conn_params = {
                "s3_staging_dir": self.connection_args["s3_staging_dir"],
                "region_name": self.connection_args["region_name"],
                "schema_name": self._database,
                "work_group": self._workgroup,
            }

            # Use explicit credentials if provided
            if self.connection_args.get("aws_access_key_id"):
                conn_params["aws_access_key_id"] = self.connection_args["aws_access_key_id"]
            if self.connection_args.get("aws_secret_access_key"):
                conn_params["aws_secret_access_key"] = self.connection_args["aws_secret_access_key"]

            self._connection = athena_connect(**conn_params)
            self.is_connected = True
            logger.info(f"Connected to Athena: {self.name}")

        except Exception as e:
            self.is_connected = False
            logger.error(f"Failed to connect to Athena: {e}")
            raise ConnectionError(f"Failed to connect to Athena: {e}")

    def disconnect(self) -> None:
        """Close the Athena connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            finally:
                self._connection = None
                self.is_connected = False
                logger.info(f"Disconnected from Athena: {self.name}")

    def check_connection(self) -> HandlerStatus:
        """Check if the Athena connection is working."""
        try:
            if not self.is_connected:
                self.connect()

            cursor = self._connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchall()
            cursor.close()

            return HandlerStatus.success({
                "database": self._database,
                "workgroup": self._workgroup,
                "region": self.connection_args["region_name"],
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
                cursor.close()
                return HandlerResponse.ok()

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return HandlerResponse.error(str(e))

    def get_tables(self) -> HandlerResponse:
        """List all tables in the current database."""
        query = f"""
            SELECT
                table_schema,
                table_name,
                table_type
            FROM information_schema.tables
            WHERE table_schema = '{self._database}'
            ORDER BY table_name
        """
        return self.native_query(query)

    def get_columns(self, table_name: str) -> HandlerResponse:
        """Get column information for a table."""
        query = f"""
            SELECT
                column_name,
                data_type,
                ordinal_position,
                is_nullable
            FROM information_schema.columns
            WHERE table_schema = '{self._database}'
                AND table_name = '{table_name}'
            ORDER BY ordinal_position
        """
        result = self.native_query(query)
        if result.success and result.data is not None:
            for idx, row in result.data.iterrows():
                result.data.at[idx, 'canonical_type'] = self.map_type(row['data_type']).value
        return result

    def _quote_identifier(self, identifier: str) -> str:
        """Quote an Athena identifier."""
        return f'"{identifier}"'
