"""Amazon Aurora PostgreSQL database handler implementation."""

import logging
from typing import Optional

import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from src.data_connectors.libs.constants import DataType, HandlerType
from src.data_connectors.libs.database_handler import MetaDatabaseHandler
from src.data_connectors.libs.response import HandlerResponse, HandlerStatus

logger = logging.getLogger(__name__)


class AuroraPostgresHandler(MetaDatabaseHandler):
    """
    Handler for Amazon Aurora PostgreSQL-compatible databases.

    Supports querying, schema introspection, and CRUD operations
    on Aurora PostgreSQL databases. Aurora PostgreSQL is wire-compatible
    with PostgreSQL, so this handler uses the psycopg2 connector.
    """

    handler_name = "aurora_postgres"
    handler_type = HandlerType.DATA
    handler_title = "Amazon Aurora PostgreSQL"
    handler_description = "Connect to Amazon Aurora PostgreSQL-compatible databases"
    handler_version = "0.1.0"

    dialect = "postgresql"

    # Map PostgreSQL types to canonical types
    type_mapping = {
        ("integer", "int", "int4", "serial"): DataType.INTEGER,
        ("bigint", "int8", "bigserial"): DataType.BIGINT,
        ("smallint", "int2", "smallserial"): DataType.SMALLINT,
        ("real", "float4"): DataType.FLOAT,
        ("double precision", "float8"): DataType.DOUBLE,
        ("numeric", "decimal"): DataType.DECIMAL,
        ("character varying", "varchar"): DataType.VARCHAR,
        ("character", "char", "bpchar"): DataType.CHAR,
        ("text",): DataType.TEXT,
        ("bytea",): DataType.BYTES,
        ("boolean", "bool"): DataType.BOOLEAN,
        ("date",): DataType.DATE,
        ("time", "timetz"): DataType.TIME,
        ("timestamp", "timestamptz"): DataType.TIMESTAMP,
        ("json", "jsonb"): DataType.JSON,
        ("array",): DataType.ARRAY,
    }

    def __init__(self, name: str, connection_args: dict):
        """
        Initialize Aurora PostgreSQL handler.

        Args:
            name: Instance name
            connection_args: Connection parameters (host, port, database, user, password, etc.)
        """
        super().__init__(name, connection_args)
        self._schema = connection_args.get("schema", "public")

    def connect(self) -> None:
        """Establish connection to Aurora PostgreSQL database."""
        if self.is_connected:
            return

        try:
            connect_params = {
                "host": self.connection_args["host"],
                "port": self.connection_args.get("port", 5432),
                "database": self.connection_args["database"],
                "user": self.connection_args["user"],
                "password": self.connection_args["password"],
                "sslmode": self.connection_args.get("sslmode", "require"),
            }

            # Add SSL root certificate if provided
            if self.connection_args.get("sslrootcert"):
                connect_params["sslrootcert"] = self.connection_args["sslrootcert"]

            self._connection = psycopg2.connect(**connect_params)
            self._connection.autocommit = True
            self.is_connected = True
            logger.info(f"Connected to Aurora PostgreSQL: {self.name}")

        except Exception as e:
            self.is_connected = False
            logger.error(f"Failed to connect to Aurora PostgreSQL: {e}")
            raise ConnectionError(f"Failed to connect to Aurora PostgreSQL: {e}")

    def disconnect(self) -> None:
        """Close the Aurora PostgreSQL connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            finally:
                self._connection = None
                self.is_connected = False
                logger.info(f"Disconnected from Aurora PostgreSQL: {self.name}")

    def check_connection(self) -> HandlerStatus:
        """Check if the Aurora PostgreSQL connection is working."""
        try:
            if not self.is_connected:
                self.connect()

            with self._connection.cursor() as cursor:
                cursor.execute("SELECT version()")
                version = cursor.fetchone()[0]

            return HandlerStatus.success({
                "version": version,
                "database": self.connection_args["database"],
                "schema": self._schema,
                "engine": "Aurora PostgreSQL",
            })

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

            with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query)

                # Check if query returns data
                if cursor.description is None:
                    # INSERT, UPDATE, DELETE, etc.
                    return HandlerResponse.ok(affected_rows=cursor.rowcount)

                # SELECT query
                rows = cursor.fetchall()
                df = pd.DataFrame(rows)

                # Get column types
                column_types = {}
                for desc in cursor.description:
                    col_name = desc.name
                    column_types[col_name] = DataType.UNKNOWN

                return HandlerResponse.table(df, column_types)

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return HandlerResponse.error(str(e))

    def get_tables(self) -> HandlerResponse:
        """List all tables in the current schema."""
        query = """
            SELECT
                table_name,
                table_type,
                pg_catalog.obj_description(
                    (quote_ident(table_schema) || '.' || quote_ident(table_name))::regclass,
                    'pg_class'
                ) as description
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY table_name
        """
        try:
            if not self.is_connected:
                self.connect()

            with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (self._schema,))
                rows = cursor.fetchall()

            df = pd.DataFrame(rows)
            return HandlerResponse.table(df)

        except Exception as e:
            return HandlerResponse.error(str(e))

    def get_columns(self, table_name: str) -> HandlerResponse:
        """Get column information for a table."""
        query = """
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length,
                numeric_precision,
                numeric_scale,
                pg_catalog.col_description(
                    (quote_ident(table_schema) || '.' || quote_ident(table_name))::regclass,
                    ordinal_position
                ) as description
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """
        try:
            if not self.is_connected:
                self.connect()

            with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (self._schema, table_name))
                rows = cursor.fetchall()

            if not rows:
                return HandlerResponse.error(f"Table '{table_name}' not found")

            # Add canonical type mapping
            for row in rows:
                row["canonical_type"] = self.map_type(row["data_type"]).value

            df = pd.DataFrame(rows)
            return HandlerResponse.columns(df)

        except Exception as e:
            return HandlerResponse.error(str(e))

    def get_primary_keys(self, table_name: str) -> HandlerResponse:
        """Get primary key columns for a table."""
        query = """
            SELECT
                kcu.column_name,
                tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = %s
                AND tc.table_name = %s
            ORDER BY kcu.ordinal_position
        """
        try:
            if not self.is_connected:
                self.connect()

            with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (self._schema, table_name))
                rows = cursor.fetchall()

            df = pd.DataFrame(rows)
            return HandlerResponse.table(df)

        except Exception as e:
            return HandlerResponse.error(str(e))

    def get_foreign_keys(self, table_name: str) -> HandlerResponse:
        """Get foreign key relationships for a table."""
        query = """
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                tc.constraint_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_schema = %s
                AND tc.table_name = %s
        """
        try:
            if not self.is_connected:
                self.connect()

            with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (self._schema, table_name))
                rows = cursor.fetchall()

            df = pd.DataFrame(rows)
            return HandlerResponse.table(df)

        except Exception as e:
            return HandlerResponse.error(str(e))

    def get_indexes(self, table_name: str) -> HandlerResponse:
        """Get indexes for a table."""
        query = """
            SELECT
                indexname,
                indexdef
            FROM pg_indexes
            WHERE schemaname = %s AND tablename = %s
        """
        try:
            if not self.is_connected:
                self.connect()

            with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (self._schema, table_name))
                rows = cursor.fetchall()

            df = pd.DataFrame(rows)
            return HandlerResponse.table(df)

        except Exception as e:
            return HandlerResponse.error(str(e))

    def get_table_statistics(self, table_name: str) -> HandlerResponse:
        """Get statistics for a table."""
        query = """
            SELECT
                pg_total_relation_size(quote_ident(%s) || '.' || quote_ident(%s)) as total_size,
                pg_table_size(quote_ident(%s) || '.' || quote_ident(%s)) as table_size,
                pg_indexes_size(quote_ident(%s) || '.' || quote_ident(%s)) as indexes_size,
                (SELECT count(*) FROM {} ) as row_count
        """.format(f'"{self._schema}"."{table_name}"')

        try:
            if not self.is_connected:
                self.connect()

            with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, (
                    self._schema, table_name,
                    self._schema, table_name,
                    self._schema, table_name,
                ))
                row = cursor.fetchone()

            df = pd.DataFrame([row])
            return HandlerResponse.table(df)

        except Exception as e:
            return HandlerResponse.error(str(e))

    def _quote_identifier(self, identifier: str) -> str:
        """Quote a PostgreSQL identifier."""
        return f'"{identifier}"'
