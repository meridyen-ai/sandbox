"""Amazon Redshift handler implementation.

Redshift is PostgreSQL-compatible, so this handler extends the PostgreSQL handler
with Redshift-specific features and optimizations.

Supports two authentication methods:
- Service Account: Traditional username/password authentication
- IAM: AWS IAM-based authentication using temporary credentials
"""

import logging
import re
from typing import Optional

import pandas as pd

from src.data_connectors.libs.constants import DataType, HandlerType
from src.data_connectors.libs.database_handler import MetaDatabaseHandler
from src.data_connectors.libs.response import HandlerResponse, HandlerStatus

logger = logging.getLogger(__name__)


class RedshiftHandler(MetaDatabaseHandler):
    """Handler for Amazon Redshift data warehouse."""

    handler_name = "redshift"
    handler_type = HandlerType.DATA
    handler_title = "Amazon Redshift"
    handler_description = "Connect to Amazon Redshift data warehouse"
    handler_version = "0.1.0"
    dialect = "redshift"

    # Redshift type mappings (PostgreSQL compatible with Redshift extensions)
    type_mapping = {
        ("smallint", "int2"): DataType.SMALLINT,
        ("integer", "int", "int4"): DataType.INTEGER,
        ("bigint", "int8"): DataType.BIGINT,
        ("real", "float4"): DataType.FLOAT,
        ("double precision", "float8", "float"): DataType.DOUBLE,
        ("decimal", "numeric"): DataType.DECIMAL,
        ("char", "character", "nchar", "bpchar"): DataType.CHAR,
        ("varchar", "character varying", "nvarchar", "text"): DataType.VARCHAR,
        ("boolean", "bool"): DataType.BOOLEAN,
        ("date",): DataType.DATE,
        ("time", "timetz"): DataType.TIME,
        ("timestamp", "timestamptz"): DataType.TIMESTAMP,
        ("super",): DataType.JSON,  # Redshift SUPER type for semi-structured data
        ("geometry", "geography"): DataType.VARCHAR,
        ("hllsketch",): DataType.VARCHAR,  # HyperLogLog sketch
        ("varbyte",): DataType.BYTES,
    }

    def __init__(self, name: str, connection_args: dict):
        super().__init__(name, connection_args)
        self._schema = connection_args.get("schema", "public")
        self._database = connection_args.get("database")
        self._auth_type = connection_args.get("auth_type", "service_account")

    def _extract_region_from_host(self, host: str) -> Optional[str]:
        """Extract AWS region from Redshift cluster endpoint."""
        # Pattern: cluster-name.xxxxx.region.redshift.amazonaws.com
        match = re.search(r'\.([a-z]{2}-[a-z]+-\d+)\.redshift\.amazonaws\.com', host)
        if match:
            return match.group(1)
        return None

    def connect(self) -> None:
        """Establish connection to Redshift."""
        if self.is_connected:
            return

        try:
            if self._auth_type == "iam":
                self._connect_iam()
            else:
                self._connect_service_account()

            self._connection.autocommit = True

            # Set search path to include the specified schema
            with self._connection.cursor() as cursor:
                cursor.execute(f"SET search_path TO {self._schema}, public")

            self.is_connected = True
            logger.info(f"Connected to Redshift: {self.name}")

        except Exception as e:
            self.is_connected = False
            logger.error(f"Failed to connect to Redshift: {e}")
            raise ConnectionError(f"Failed to connect to Redshift: {e}")

    def _connect_service_account(self) -> None:
        """Connect using traditional username/password (Service Account)."""
        import psycopg2

        self._connection = psycopg2.connect(
            host=self.connection_args["host"],
            port=self.connection_args.get("port", 5439),
            database=self.connection_args["database"],
            user=self.connection_args["user"],
            password=self.connection_args["password"],
            sslmode=self.connection_args.get("sslmode", "require"),
        )

    def _connect_iam(self) -> None:
        """Connect using IAM authentication."""
        import redshift_connector

        host = self.connection_args["host"]
        region = self.connection_args.get("region") or self._extract_region_from_host(host)

        if not region:
            raise ValueError("AWS region is required for IAM authentication. "
                           "Provide it explicitly or use a standard Redshift endpoint.")

        conn_params = {
            "host": host,
            "port": self.connection_args.get("port", 5439),
            "database": self.connection_args["database"],
            "db_user": self.connection_args["db_user"],
            "cluster_identifier": self.connection_args["cluster_identifier"],
            "region": region,
            "iam": True,
            "ssl": True,
        }

        # Use explicit AWS credentials if provided, otherwise use default credentials chain
        if self.connection_args.get("aws_access_key_id"):
            conn_params["access_key_id"] = self.connection_args["aws_access_key_id"]
        if self.connection_args.get("aws_secret_access_key"):
            conn_params["secret_access_key"] = self.connection_args["aws_secret_access_key"]

        self._connection = redshift_connector.connect(**conn_params)

    def disconnect(self) -> None:
        """Close the Redshift connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            finally:
                self._connection = None
                self.is_connected = False
                logger.info(f"Disconnected from Redshift: {self.name}")

    def check_connection(self) -> HandlerStatus:
        """Check if the Redshift connection is working."""
        try:
            if not self.is_connected:
                self.connect()

            with self._connection.cursor() as cursor:
                cursor.execute("SELECT version()")
                version = cursor.fetchone()[0]

            return HandlerStatus.success({
                "version": version,
                "database": self._database,
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

            if cursor.description is None:
                rowcount = cursor.rowcount
                cursor.close()
                return HandlerResponse.ok(affected_rows=rowcount)

            # Get column names from cursor description
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            cursor.close()

            # Convert to list of dicts for DataFrame
            data = [dict(zip(columns, row)) for row in rows]
            df = pd.DataFrame(data)
            return HandlerResponse.table(df)

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return HandlerResponse.error(str(e))

    def get_tables(self) -> HandlerResponse:
        """List all tables in the current schema."""
        query = f"""
            SELECT
                schemaname AS table_schema,
                tablename AS table_name,
                'BASE TABLE' AS table_type
            FROM pg_tables
            WHERE schemaname = '{self._schema}'
            UNION ALL
            SELECT
                schemaname AS table_schema,
                viewname AS table_name,
                'VIEW' AS table_type
            FROM pg_views
            WHERE schemaname = '{self._schema}'
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
                column_default,
                is_nullable,
                character_maximum_length AS max_length,
                numeric_precision,
                numeric_scale
            FROM information_schema.columns
            WHERE table_schema = '{self._schema}'
                AND table_name = '{table_name}'
            ORDER BY ordinal_position
        """
        result = self.native_query(query)
        if result.success and result.data is not None:
            for idx, row in result.data.iterrows():
                result.data.at[idx, 'canonical_type'] = self.map_type(row['data_type']).value
        return result

    def get_table_statistics(self, table_name: str) -> HandlerResponse:
        """Get statistics for a table (Redshift-specific)."""
        query = f"""
            SELECT
                t.tablename AS table_name,
                t.size AS size_mb,
                t.tbl_rows AS row_count,
                t.sortkey1 AS sort_key,
                t.diststyle AS distribution_style
            FROM svv_table_info t
            WHERE t.schema = '{self._schema}'
                AND t.tablename = '{table_name}'
        """
        return self.native_query(query)

    def get_primary_keys(self, table_name: str) -> HandlerResponse:
        """Get primary key columns for a table."""
        query = f"""
            SELECT
                tc.constraint_name,
                kcu.column_name,
                kcu.ordinal_position
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = '{self._schema}'
                AND tc.table_name = '{table_name}'
            ORDER BY kcu.ordinal_position
        """
        return self.native_query(query)

    def _quote_identifier(self, identifier: str) -> str:
        """Quote a Redshift identifier."""
        return f'"{identifier}"'
