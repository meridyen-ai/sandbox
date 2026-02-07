"""SAP HANA database handler implementation."""

import logging
from typing import Optional

import pandas as pd
from hdbcli import dbapi

from src.data_connectors.libs.constants import DataType, HandlerType
from src.data_connectors.libs.database_handler import MetaDatabaseHandler
from src.data_connectors.libs.response import HandlerResponse, HandlerStatus

logger = logging.getLogger(__name__)


class SAPHanaHandler(MetaDatabaseHandler):
    """Handler for SAP HANA databases."""

    handler_name = "sap_hana"
    handler_type = HandlerType.DATA
    handler_title = "SAP HANA"
    handler_description = "Connect to SAP HANA databases"
    handler_version = "0.1.0"
    dialect = "hana"

    type_mapping = {
        ("tinyint",): DataType.SMALLINT,
        ("smallint",): DataType.SMALLINT,
        ("integer", "int"): DataType.INTEGER,
        ("bigint",): DataType.BIGINT,
        ("real", "smalldecimal"): DataType.FLOAT,
        ("double",): DataType.DOUBLE,
        ("decimal", "numeric"): DataType.DECIMAL,
        ("char", "nchar"): DataType.CHAR,
        ("varchar", "nvarchar", "alphanum", "shorttext"): DataType.VARCHAR,
        ("clob", "nclob", "text"): DataType.TEXT,
        ("blob", "varbinary"): DataType.BLOB,
        ("boolean",): DataType.BOOLEAN,
        ("date",): DataType.DATE,
        ("time",): DataType.TIME,
        ("timestamp", "seconddate"): DataType.TIMESTAMP,
        ("st_geometry", "st_point"): DataType.VARCHAR,
    }

    def __init__(self, name: str, connection_args: dict):
        super().__init__(name, connection_args)
        self._schema = connection_args.get("schema")

    def connect(self) -> None:
        """Establish connection to SAP HANA."""
        if self.is_connected:
            return

        try:
            conn_params = {
                "address": self.connection_args["host"],
                "port": self.connection_args["port"],
                "user": self.connection_args["user"],
                "password": self.connection_args["password"],
            }

            if self.connection_args.get("encrypt", True):
                conn_params["encrypt"] = True
                conn_params["sslValidateCertificate"] = False

            self._connection = dbapi.connect(**conn_params)

            # Set default schema if specified
            if self._schema:
                cursor = self._connection.cursor()
                cursor.execute(f"SET SCHEMA {self._schema}")
                cursor.close()

            self.is_connected = True
            logger.info(f"Connected to SAP HANA: {self.name}")

        except Exception as e:
            self.is_connected = False
            logger.error(f"Failed to connect to SAP HANA: {e}")
            raise ConnectionError(f"Failed to connect to SAP HANA: {e}")

    def disconnect(self) -> None:
        """Close the SAP HANA connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            finally:
                self._connection = None
                self.is_connected = False
                logger.info(f"Disconnected from SAP HANA: {self.name}")

    def check_connection(self) -> HandlerStatus:
        """Check if the SAP HANA connection is working."""
        try:
            if not self.is_connected:
                self.connect()

            cursor = self._connection.cursor()
            cursor.execute("SELECT VERSION FROM SYS.M_DATABASE")
            row = cursor.fetchone()
            version = row[0] if row else "Unknown"
            cursor.close()

            return HandlerStatus.success({
                "version": version,
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
                affected = cursor.rowcount
                self._connection.commit()
                cursor.close()
                return HandlerResponse.ok(affected_rows=affected)

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return HandlerResponse.error(str(e))

    def get_tables(self) -> HandlerResponse:
        """List all tables in the current schema."""
        schema_filter = f"WHERE SCHEMA_NAME = '{self._schema}'" if self._schema else "WHERE SCHEMA_NAME = CURRENT_SCHEMA"
        query = f"""
            SELECT
                SCHEMA_NAME AS table_schema,
                TABLE_NAME AS table_name,
                TABLE_TYPE AS table_type
            FROM SYS.TABLES
            {schema_filter}
            ORDER BY TABLE_NAME
        """
        return self.native_query(query)

    def get_columns(self, table_name: str) -> HandlerResponse:
        """Get column information for a table."""
        schema_filter = f"AND SCHEMA_NAME = '{self._schema}'" if self._schema else "AND SCHEMA_NAME = CURRENT_SCHEMA"
        query = f"""
            SELECT
                COLUMN_NAME AS column_name,
                DATA_TYPE_NAME AS data_type,
                POSITION AS ordinal_position,
                DEFAULT_VALUE AS column_default,
                IS_NULLABLE AS is_nullable,
                LENGTH AS max_length,
                SCALE AS numeric_scale,
                COMMENTS AS description
            FROM SYS.TABLE_COLUMNS
            WHERE TABLE_NAME = '{table_name}'
                {schema_filter}
            ORDER BY POSITION
        """
        result = self.native_query(query)
        if result.success and result.data is not None:
            for idx, row in result.data.iterrows():
                result.data.at[idx, 'canonical_type'] = self.map_type(row['data_type']).value
        return result

    def get_primary_keys(self, table_name: str) -> HandlerResponse:
        """Get primary key columns for a table."""
        schema_filter = f"AND SCHEMA_NAME = '{self._schema}'" if self._schema else "AND SCHEMA_NAME = CURRENT_SCHEMA"
        query = f"""
            SELECT
                CONSTRAINT_NAME AS constraint_name,
                COLUMN_NAME AS column_name,
                POSITION AS ordinal_position
            FROM SYS.CONSTRAINTS
            WHERE TABLE_NAME = '{table_name}'
                AND IS_PRIMARY_KEY = 'TRUE'
                {schema_filter}
            ORDER BY POSITION
        """
        return self.native_query(query)

    def _quote_identifier(self, identifier: str) -> str:
        """Quote a SAP HANA identifier."""
        return f'"{identifier}"'
