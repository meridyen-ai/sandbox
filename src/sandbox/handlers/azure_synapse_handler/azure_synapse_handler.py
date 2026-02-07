"""Azure Synapse Analytics handler implementation.

Azure Synapse uses the same T-SQL dialect as SQL Server, so this handler
is similar to the SQL Server handler with Synapse-specific optimizations.
"""

import logging
from typing import Optional

import pandas as pd
import pyodbc

from src.data_connectors.libs.constants import DataType, HandlerType
from src.data_connectors.libs.database_handler import MetaDatabaseHandler
from src.data_connectors.libs.response import HandlerResponse, HandlerStatus

logger = logging.getLogger(__name__)


class AzureSynapseHandler(MetaDatabaseHandler):
    """Handler for Azure Synapse Analytics."""

    handler_name = "azure_synapse"
    handler_type = HandlerType.DATA
    handler_title = "Azure Synapse"
    handler_description = "Connect to Azure Synapse Analytics"
    handler_version = "0.1.0"
    dialect = "mssql"

    type_mapping = {
        ("tinyint",): DataType.SMALLINT,
        ("smallint",): DataType.SMALLINT,
        ("int",): DataType.INTEGER,
        ("bigint",): DataType.BIGINT,
        ("real",): DataType.FLOAT,
        ("float",): DataType.DOUBLE,
        ("decimal", "numeric", "money", "smallmoney"): DataType.DECIMAL,
        ("char", "nchar"): DataType.CHAR,
        ("varchar", "nvarchar"): DataType.VARCHAR,
        ("text", "ntext"): DataType.TEXT,
        ("binary", "varbinary"): DataType.BYTES,
        ("date",): DataType.DATE,
        ("time",): DataType.TIME,
        ("datetime", "datetime2", "smalldatetime"): DataType.DATETIME,
        ("datetimeoffset",): DataType.TIMESTAMP,
        ("bit",): DataType.BOOLEAN,
        ("uniqueidentifier",): DataType.VARCHAR,
    }

    def __init__(self, name: str, connection_args: dict):
        super().__init__(name, connection_args)
        self._database = connection_args.get("database")

    def connect(self) -> None:
        """Establish connection to Azure Synapse."""
        if self.is_connected:
            return

        try:
            host = self.connection_args["host"]
            port = self.connection_args.get("port", 1433)
            database = self.connection_args["database"]
            user = self.connection_args["user"]
            password = self.connection_args["password"]
            encrypt = "yes" if self.connection_args.get("encrypt", True) else "no"

            conn_str = (
                f"DRIVER={{ODBC Driver 18 for SQL Server}};"
                f"SERVER={host},{port};"
                f"DATABASE={database};"
                f"UID={user};"
                f"PWD={password};"
                f"Encrypt={encrypt};"
                f"TrustServerCertificate=no;"
                f"Connection Timeout=30;"
            )

            self._connection = pyodbc.connect(conn_str)
            self._connection.autocommit = True
            self.is_connected = True
            logger.info(f"Connected to Azure Synapse: {self.name}")

        except Exception as e:
            self.is_connected = False
            logger.error(f"Failed to connect to Azure Synapse: {e}")
            raise ConnectionError(f"Failed to connect to Azure Synapse: {e}")

    def disconnect(self) -> None:
        """Close the Azure Synapse connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            finally:
                self._connection = None
                self.is_connected = False
                logger.info(f"Disconnected from Azure Synapse: {self.name}")

    def check_connection(self) -> HandlerStatus:
        """Check if the Azure Synapse connection is working."""
        try:
            if not self.is_connected:
                self.connect()

            cursor = self._connection.cursor()
            cursor.execute("SELECT @@VERSION")
            version = cursor.fetchone()[0]
            cursor.close()

            return HandlerStatus.success({
                "version": version.split("\n")[0],
                "database": self._database,
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
                cursor.close()
                return HandlerResponse.ok(affected_rows=affected)

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return HandlerResponse.error(str(e))

    def get_tables(self) -> HandlerResponse:
        """List all tables in the database."""
        query = """
            SELECT
                TABLE_SCHEMA AS table_schema,
                TABLE_NAME AS table_name,
                TABLE_TYPE AS table_type
            FROM INFORMATION_SCHEMA.TABLES
            ORDER BY TABLE_SCHEMA, TABLE_NAME
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
                NUMERIC_SCALE AS numeric_scale
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = '{table_name}'
            ORDER BY ORDINAL_POSITION
        """
        result = self.native_query(query)
        if result.success and result.data is not None:
            for idx, row in result.data.iterrows():
                result.data.at[idx, 'canonical_type'] = self.map_type(row['data_type']).value
        return result

    def get_table_statistics(self, table_name: str) -> HandlerResponse:
        """Get statistics for a table (Synapse-specific)."""
        query = f"""
            SELECT
                t.name AS table_name,
                p.rows AS row_count,
                SUM(a.total_pages) * 8 AS total_space_kb,
                SUM(a.used_pages) * 8 AS used_space_kb
            FROM sys.tables t
            INNER JOIN sys.indexes i ON t.object_id = i.object_id
            INNER JOIN sys.partitions p ON i.object_id = p.object_id AND i.index_id = p.index_id
            INNER JOIN sys.allocation_units a ON p.partition_id = a.container_id
            WHERE t.name = '{table_name}'
                AND i.index_id <= 1
            GROUP BY t.name, p.rows
        """
        return self.native_query(query)

    def _quote_identifier(self, identifier: str) -> str:
        """Quote an Azure Synapse identifier."""
        return f"[{identifier}]"
