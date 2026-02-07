"""MySQL database handler implementation."""

import logging
from typing import Any, List, Optional

import pandas as pd
import mysql.connector
from mysql.connector import Error as MySQLError

from src.data_connectors.libs.constants import DataType, HandlerType
from src.data_connectors.libs.database_handler import MetaDatabaseHandler
from src.data_connectors.libs.response import HandlerResponse, HandlerStatus

logger = logging.getLogger(__name__)


class MySQLHandler(MetaDatabaseHandler):
    """
    Handler for MySQL and MariaDB databases.

    Supports querying, schema introspection, and CRUD operations.
    """

    handler_name = "mysql"
    handler_type = HandlerType.DATA
    handler_title = "MySQL"
    handler_description = "Connect to MySQL and MariaDB databases"
    handler_version = "0.1.0"

    dialect = "mysql"

    # Map MySQL types to canonical types
    type_mapping = {
        ("tinyint",): DataType.SMALLINT,
        ("smallint",): DataType.SMALLINT,
        ("mediumint", "int", "integer"): DataType.INTEGER,
        ("bigint",): DataType.BIGINT,
        ("float",): DataType.FLOAT,
        ("double", "real"): DataType.DOUBLE,
        ("decimal", "numeric"): DataType.DECIMAL,
        ("char",): DataType.CHAR,
        ("varchar",): DataType.VARCHAR,
        ("tinytext", "text", "mediumtext", "longtext"): DataType.TEXT,
        ("binary", "varbinary"): DataType.BYTES,
        ("tinyblob", "blob", "mediumblob", "longblob"): DataType.BLOB,
        ("date",): DataType.DATE,
        ("time",): DataType.TIME,
        ("datetime",): DataType.DATETIME,
        ("timestamp",): DataType.TIMESTAMP,
        ("boolean", "bool"): DataType.BOOLEAN,
        ("json",): DataType.JSON,
    }

    def __init__(self, name: str, connection_args: dict):
        """
        Initialize MySQL handler.

        Args:
            name: Instance name
            connection_args: Connection parameters
        """
        super().__init__(name, connection_args)
        self._database = connection_args.get("database")

    def connect(self) -> None:
        """Establish connection to MySQL database."""
        if self.is_connected:
            return

        try:
            config = {
                "host": self.connection_args["host"],
                "port": self.connection_args.get("port", 3306),
                "database": self.connection_args["database"],
                "user": self.connection_args["user"],
                "password": self.connection_args["password"],
                "connection_timeout": 10,
                "use_pure": True,
                "collation": "utf8mb4_general_ci",
            }

            # Handle SSL
            ssl = self.connection_args.get("ssl")
            if ssl:
                config["ssl_disabled"] = False
                if self.connection_args.get("ssl_ca"):
                    config["ssl_ca"] = self.connection_args["ssl_ca"]
            elif ssl is False:
                config["ssl_disabled"] = True

            self._connection = mysql.connector.connect(**config)
            self._connection.autocommit = True
            self.is_connected = True
            logger.info(f"Connected to MySQL: {self.name}")

        except MySQLError as e:
            self.is_connected = False
            logger.error(f"Failed to connect to MySQL: {e}")
            raise ConnectionError(f"Failed to connect to MySQL: {e}")

    def disconnect(self) -> None:
        """Close the MySQL connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            finally:
                self._connection = None
                self.is_connected = False
                logger.info(f"Disconnected from MySQL: {self.name}")

    def check_connection(self) -> HandlerStatus:
        """Check if the MySQL connection is working."""
        try:
            if not self.is_connected:
                self.connect()

            if self._connection.is_connected():
                server_info = self._connection.get_server_info()
                return HandlerStatus.success({
                    "version": server_info,
                    "database": self._database,
                })
            else:
                return HandlerStatus.error("Connection lost")

        except Exception as e:
            return HandlerStatus.error(str(e))

    def native_query(self, query: str) -> HandlerResponse:
        """
        Execute a raw SQL query.

        Args:
            query: SQL query string

        Returns:
            HandlerResponse with query results
        """
        try:
            if not self.is_connected:
                self.connect()

            with self._connection.cursor(dictionary=True, buffered=True) as cursor:
                cursor.execute(query)

                if cursor.with_rows:
                    rows = cursor.fetchall()
                    df = pd.DataFrame(rows)
                    return HandlerResponse.table(df)
                else:
                    return HandlerResponse.ok(affected_rows=cursor.rowcount)

        except MySQLError as e:
            logger.error(f"Query failed: {e}")
            if self._connection and self._connection.is_connected():
                self._connection.rollback()
            return HandlerResponse.error(str(e))

    def get_tables(self) -> HandlerResponse:
        """List all tables in the current database."""
        query = """
            SELECT
                TABLE_SCHEMA AS table_schema,
                TABLE_NAME AS table_name,
                TABLE_TYPE AS table_type
            FROM information_schema.TABLES
            WHERE TABLE_TYPE IN ('BASE TABLE', 'VIEW')
                AND TABLE_SCHEMA = DATABASE()
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
                COLUMN_COMMENT AS description
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = '{table_name}'
            ORDER BY ORDINAL_POSITION
        """
        result = self.native_query(query)

        if result.success and result.data is not None:
            # Add canonical type mapping
            for idx, row in result.data.iterrows():
                result.data.at[idx, 'canonical_type'] = self.map_type(
                    row['data_type']
                ).value

        return result

    def get_primary_keys(self, table_name: str) -> HandlerResponse:
        """Get primary key columns for a table."""
        query = f"""
            SELECT
                tc.TABLE_NAME AS table_name,
                kcu.COLUMN_NAME AS column_name,
                kcu.ORDINAL_POSITION AS ordinal_position,
                tc.CONSTRAINT_NAME AS constraint_name
            FROM information_schema.TABLE_CONSTRAINTS tc
            INNER JOIN information_schema.KEY_COLUMN_USAGE kcu
                ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                AND tc.TABLE_NAME = kcu.TABLE_NAME
            WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                AND tc.TABLE_SCHEMA = DATABASE()
                AND tc.TABLE_NAME = '{table_name}'
            ORDER BY kcu.ORDINAL_POSITION
        """
        return self.native_query(query)

    def get_foreign_keys(self, table_name: str) -> HandlerResponse:
        """Get foreign key relationships for a table."""
        query = f"""
            SELECT
                kcu.REFERENCED_TABLE_NAME AS parent_table_name,
                kcu.REFERENCED_COLUMN_NAME AS parent_column_name,
                kcu.TABLE_NAME AS child_table_name,
                kcu.COLUMN_NAME AS child_column_name,
                kcu.CONSTRAINT_NAME AS constraint_name
            FROM information_schema.KEY_COLUMN_USAGE kcu
            WHERE kcu.TABLE_SCHEMA = DATABASE()
                AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
                AND kcu.TABLE_NAME = '{table_name}'
            ORDER BY kcu.CONSTRAINT_NAME
        """
        return self.native_query(query)

    def get_indexes(self, table_name: str) -> HandlerResponse:
        """Get indexes for a table."""
        query = f"""
            SELECT
                INDEX_NAME AS index_name,
                COLUMN_NAME AS column_name,
                NON_UNIQUE AS non_unique,
                SEQ_IN_INDEX AS seq_in_index,
                INDEX_TYPE AS index_type
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = '{table_name}'
            ORDER BY INDEX_NAME, SEQ_IN_INDEX
        """
        return self.native_query(query)

    def get_table_statistics(self, table_name: str) -> HandlerResponse:
        """Get statistics for a table."""
        query = f"""
            SELECT
                TABLE_NAME AS table_name,
                TABLE_ROWS AS row_count,
                DATA_LENGTH AS data_size,
                INDEX_LENGTH AS index_size,
                (DATA_LENGTH + INDEX_LENGTH) AS total_size,
                TABLE_COMMENT AS description
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = '{table_name}'
        """
        return self.native_query(query)

    def _quote_identifier(self, identifier: str) -> str:
        """Quote a MySQL identifier."""
        return f"`{identifier}`"
