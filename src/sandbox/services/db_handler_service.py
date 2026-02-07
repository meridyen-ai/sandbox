"""
Database Handler Service - Multi-database connection management.

Provides a unified interface for connecting to and testing various database types.
Each handler uses the appropriate Python driver directly.

Supported data sources:
- Cloud Data Platforms: Snowflake, Databricks, Amazon Redshift, Google BigQuery, Azure Synapse
- Query Engines: Amazon Athena, Dremio, Presto, Starburst, Trino
- Databases: PostgreSQL, MySQL, SQL Server, Oracle, SAP HANA, SingleStore, Teradata,
             MariaDB, CockroachDB, ClickHouse
- File Sources: CSV File, Google Sheets
- Other Sources: Looker, Denodo
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


@dataclass
class ConnectionArg:
    """Definition of a connection argument."""
    name: str
    type: str  # 'string', 'integer', 'boolean', 'password', 'text', 'select'
    label: str
    description: str
    required: bool = True
    secret: bool = False
    default: Any = None
    options: List[Dict[str, str]] = None  # For 'select' type: [{"value": "x", "label": "X"}]
    depends_on: Dict[str, Any] = None  # Conditional visibility: {"field": "auth_type", "values": ["password"]}

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "name": self.name,
            "type": self.type,
            "label": self.label,
            "description": self.description,
            "required": self.required,
            "secret": self.secret,
            "default": self.default,
        }
        if self.options:
            result["options"] = self.options
        if self.depends_on:
            result["depends_on"] = self.depends_on
        return result


@dataclass
class HandlerInfo:
    """Information about a database handler."""
    name: str
    type: str  # 'database', 'datawarehouse'
    title: str
    description: str
    icon: Optional[str] = None
    connection_args: List[ConnectionArg] = None
    available: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "available": self.available,
            "connection_args": [
                {
                    "name": arg.name,
                    "type": arg.type,
                    "label": arg.label,
                    "description": arg.description,
                    "required": arg.required,
                    "secret": arg.secret,
                    "default": arg.default,
                }
                for arg in (self.connection_args or [])
            ],
        }


@dataclass
class ConnectionTestResult:
    """Result of a connection test."""
    success: bool
    message: str
    error: Optional[str] = None


class BaseDBHandler(ABC):
    """Abstract base class for database handlers."""

    name: str = ""
    type: str = "database"
    title: str = ""
    description: str = ""
    icon: str = ""
    connection_args: List[ConnectionArg] = []

    @classmethod
    def get_info(cls) -> HandlerInfo:
        """Get handler information."""
        return HandlerInfo(
            name=cls.name,
            type=cls.type,
            title=cls.title,
            description=cls.description,
            icon=cls.icon,
            connection_args=cls.connection_args,
            available=cls.is_available(),
        )

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Check if the required driver is installed."""
        pass

    @classmethod
    @abstractmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        """Test a database connection."""
        pass

    @classmethod
    @abstractmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get list of tables from the database."""
        pass

    @classmethod
    @abstractmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        """Get columns for a specific table."""
        pass


class PostgresHandler(BaseDBHandler):
    """PostgreSQL database handler."""

    name = "postgres"
    type = "database"
    title = "PostgreSQL"
    description = "Open-source relational database"
    icon = "postgres"
    connection_args = [
        ConnectionArg("host", "string", "Host", "Database server hostname", required=True),
        ConnectionArg("port", "integer", "Port", "Database port (default: 5432)", required=False, default=5432),
        ConnectionArg("database", "string", "Database", "Database name", required=True),
        ConnectionArg("username", "string", "Username", "Database username", required=True),
        ConnectionArg("password", "password", "Password", "Database password", required=True, secret=True),
        ConnectionArg("ssl_mode", "string", "SSL Mode", "SSL connection mode (disable, require, verify-ca, verify-full)", required=False),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import psycopg2
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import psycopg2

            conn_params = {
                "host": connection_data.get("host"),
                "port": connection_data.get("port", 5432),
                "dbname": connection_data.get("database"),
                "user": connection_data.get("username"),
                "password": connection_data.get("password"),
                "connect_timeout": 10,
            }

            if connection_data.get("ssl_mode"):
                conn_params["sslmode"] = connection_data["ssl_mode"]

            conn = psycopg2.connect(**conn_params)
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="PostgreSQL driver not installed", error="psycopg2 not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        import psycopg2

        conn = psycopg2.connect(
            host=connection_data.get("host"),
            port=connection_data.get("port", 5432),
            dbname=connection_data.get("database"),
            user=connection_data.get("username"),
            password=connection_data.get("password"),
        )

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
                ORDER BY table_schema, table_name
            """)
            tables = [
                {"schema": row[0], "name": row[1], "type": row[2]}
                for row in cursor.fetchall()
            ]
            return tables
        finally:
            conn.close()

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        import psycopg2

        conn = psycopg2.connect(
            host=connection_data.get("host"),
            port=connection_data.get("port", 5432),
            dbname=connection_data.get("database"),
            user=connection_data.get("username"),
            password=connection_data.get("password"),
        )

        try:
            cursor = conn.cursor()
            # Parse schema.table if provided
            if "." in table_name:
                schema, table = table_name.split(".", 1)
            else:
                schema = "public"
                table = table_name

            cursor.execute("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
            """, (schema, table))

            columns = [
                {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2] == "YES",
                    "default": row[3],
                }
                for row in cursor.fetchall()
            ]
            return columns
        finally:
            conn.close()


class MySQLHandler(BaseDBHandler):
    """MySQL database handler."""

    name = "mysql"
    type = "database"
    title = "MySQL"
    description = "Popular open-source relational database"
    icon = "mysql"
    connection_args = [
        ConnectionArg("host", "string", "Host", "Database server hostname", required=True),
        ConnectionArg("port", "integer", "Port", "Database port (default: 3306)", required=False, default=3306),
        ConnectionArg("database", "string", "Database", "Database name", required=True),
        ConnectionArg("username", "string", "Username", "Database username", required=True),
        ConnectionArg("password", "password", "Password", "Database password", required=True, secret=True),
        ConnectionArg("ssl_mode", "string", "SSL Mode", "Use SSL (true/false)", required=False),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import mysql.connector
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import mysql.connector

            conn = mysql.connector.connect(
                host=connection_data.get("host"),
                port=connection_data.get("port", 3306),
                database=connection_data.get("database"),
                user=connection_data.get("username"),
                password=connection_data.get("password"),
                connection_timeout=10,
            )
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="MySQL driver not installed", error="mysql-connector-python not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        import mysql.connector

        conn = mysql.connector.connect(
            host=connection_data.get("host"),
            port=connection_data.get("port", 3306),
            database=connection_data.get("database"),
            user=connection_data.get("username"),
            password=connection_data.get("password"),
        )

        try:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            tables = [
                {"schema": connection_data.get("database"), "name": row[0], "type": "TABLE"}
                for row in cursor.fetchall()
            ]
            return tables
        finally:
            conn.close()

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        import mysql.connector

        conn = mysql.connector.connect(
            host=connection_data.get("host"),
            port=connection_data.get("port", 3306),
            database=connection_data.get("database"),
            user=connection_data.get("username"),
            password=connection_data.get("password"),
        )

        try:
            cursor = conn.cursor()
            # Handle schema.table format - extract just the table name if schema matches database
            actual_table = table_name
            if "." in table_name:
                parts = table_name.split(".", 1)
                schema = parts[0]
                table = parts[1]
                # If schema matches the connected database, use just the table name
                if schema == connection_data.get("database"):
                    actual_table = table
                else:
                    actual_table = table  # MySQL uses database as schema, just use table name
            cursor.execute(f"DESCRIBE `{actual_table}`")
            columns = [
                {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2] == "YES",
                    "default": row[4],
                }
                for row in cursor.fetchall()
            ]
            return columns
        finally:
            conn.close()


class SQLServerHandler(BaseDBHandler):
    """Microsoft SQL Server handler."""

    name = "sqlserver"
    type = "database"
    title = "SQL Server"
    description = "Microsoft SQL Server database"
    icon = "sqlserver"
    connection_args = [
        ConnectionArg("host", "string", "Host", "Database server hostname", required=True),
        ConnectionArg("port", "integer", "Port", "Database port (default: 1433)", required=False, default=1433),
        ConnectionArg("database", "string", "Database", "Database name", required=True),
        ConnectionArg("username", "string", "Username", "Database username", required=True),
        ConnectionArg("password", "password", "Password", "Database password", required=True, secret=True),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import pymssql
            return True
        except ImportError:
            try:
                import pyodbc
                return True
            except ImportError:
                return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import pymssql

            conn = pymssql.connect(
                server=connection_data.get("host"),
                port=connection_data.get("port", 1433),
                database=connection_data.get("database"),
                user=connection_data.get("username"),
                password=connection_data.get("password"),
                login_timeout=10,
            )
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="SQL Server driver not installed", error="pymssql not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        import pymssql

        conn = pymssql.connect(
            server=connection_data.get("host"),
            port=connection_data.get("port", 1433),
            database=connection_data.get("database"),
            user=connection_data.get("username"),
            password=connection_data.get("password"),
        )

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """)
            tables = [
                {"schema": row[0], "name": row[1], "type": row[2]}
                for row in cursor.fetchall()
            ]
            return tables
        finally:
            conn.close()

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        import pymssql

        conn = pymssql.connect(
            server=connection_data.get("host"),
            port=connection_data.get("port", 1433),
            database=connection_data.get("database"),
            user=connection_data.get("username"),
            password=connection_data.get("password"),
        )

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
            """, (table_name,))

            columns = [
                {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2] == "YES",
                    "default": row[3],
                }
                for row in cursor.fetchall()
            ]
            return columns
        finally:
            conn.close()


class SnowflakeHandler(BaseDBHandler):
    """Snowflake data warehouse handler."""

    name = "snowflake"
    type = "datawarehouse"
    title = "Snowflake"
    description = "Cloud data warehouse"
    icon = "snowflake"
    connection_args = [
        ConnectionArg("account", "string", "Account name or your Snowflake URL", "Snowflake account identifier (e.g., xy12345.us-east-1 or https://xy12345.snowflakecomputing.com)", required=True),
        ConnectionArg("auth_type", "select", "Authentication type", "Select authentication method", required=True, default="password", options=[
            {"value": "password", "label": "Personal Access Token"},
            {"value": "key_pair", "label": "Key Pair"},
            {"value": "service_account", "label": "Service Account"},
            {"value": "external_oauth", "label": "External OAuth"},
            {"value": "external_oauth_pkce", "label": "External OAuth with PKCE"},
            {"value": "oauth_client_credentials", "label": "OAuth Client Credentials"},
        ]),
        # Personal Access Token / Password auth fields
        ConnectionArg("user", "string", "User", "Snowflake username", required=True, depends_on={"field": "auth_type", "values": ["password", "key_pair"]}),
        ConnectionArg("password", "password", "Password", "Snowflake password or personal access token", required=True, secret=True, depends_on={"field": "auth_type", "values": ["password"]}),
        # Key Pair auth fields
        ConnectionArg("private_key", "text", "Private Key", "RSA private key (PEM format)", required=True, secret=True, depends_on={"field": "auth_type", "values": ["key_pair"]}),
        ConnectionArg("private_key_passphrase", "password", "Private Key Passphrase", "Passphrase for encrypted private key (optional)", required=False, secret=True, depends_on={"field": "auth_type", "values": ["key_pair"]}),
        # OAuth fields
        ConnectionArg("oauth_token", "password", "OAuth Token", "OAuth access token", required=True, secret=True, depends_on={"field": "auth_type", "values": ["external_oauth", "external_oauth_pkce", "oauth_client_credentials"]}),
        # Common fields
        ConnectionArg("role", "string", "Role", "User role (optional)", required=False),
        ConnectionArg("warehouse", "string", "Warehouse", "Compute warehouse name", required=True),
        ConnectionArg("database", "string", "Database", "Database name (optional)", required=False),
        ConnectionArg("schema", "string", "Schema", "Schema name (default: PUBLIC)", required=False, default="PUBLIC"),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import snowflake.connector
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import snowflake.connector

            conn = snowflake.connector.connect(
                account=connection_data.get("account"),
                user=connection_data.get("user") or connection_data.get("username"),
                password=connection_data.get("password"),
                warehouse=connection_data.get("warehouse"),
                database=connection_data.get("database"),
                schema=connection_data.get("schema", "PUBLIC"),
                role=connection_data.get("role"),
                login_timeout=10,
            )
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="Snowflake driver not installed", error="snowflake-connector-python not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        import snowflake.connector

        conn = snowflake.connector.connect(
            account=connection_data.get("account"),
            user=connection_data.get("user") or connection_data.get("username"),
            password=connection_data.get("password"),
            warehouse=connection_data.get("warehouse"),
            database=connection_data.get("database"),
            schema=connection_data.get("schema", "PUBLIC"),
        )

        try:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            tables = [
                {"schema": row[3], "name": row[1], "type": "TABLE"}
                for row in cursor.fetchall()
            ]
            return tables
        finally:
            conn.close()

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        import snowflake.connector

        conn = snowflake.connector.connect(
            account=connection_data.get("account"),
            user=connection_data.get("user") or connection_data.get("username"),
            password=connection_data.get("password"),
            warehouse=connection_data.get("warehouse"),
            database=connection_data.get("database"),
            schema=connection_data.get("schema", "PUBLIC"),
        )

        try:
            cursor = conn.cursor()
            cursor.execute(f"DESCRIBE TABLE {table_name}")
            columns = [
                {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[3] == "Y",
                    "default": row[4],
                }
                for row in cursor.fetchall()
            ]
            return columns
        finally:
            conn.close()


class BigQueryHandler(BaseDBHandler):
    """Google BigQuery handler."""

    name = "bigquery"
    type = "datawarehouse"
    title = "Google BigQuery"
    description = "Google Cloud data warehouse"
    icon = "bigquery"
    connection_args = [
        ConnectionArg("project_id", "string", "Billing Project Id", "Google Cloud billing project ID", required=True),
        ConnectionArg("additional_projects", "string", "Additional Projects (Optional)", "Comma-separated list of additional project IDs", required=False),
        ConnectionArg("credentials_json", "text", "Service account", "Service account credentials JSON", required=True, secret=True),
        ConnectionArg("dataset", "string", "Default Dataset", "Default dataset name (optional)", required=False),
        ConnectionArg("location", "string", "Location", "BigQuery location (e.g., US, EU)", required=False),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            from google.cloud import bigquery
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            from google.cloud import bigquery
            from google.oauth2 import service_account
            import json

            credentials_json = connection_data.get("credentials_json")
            if isinstance(credentials_json, str):
                credentials_info = json.loads(credentials_json)
            else:
                credentials_info = credentials_json

            credentials = service_account.Credentials.from_service_account_info(credentials_info)
            client = bigquery.Client(
                project=connection_data.get("project_id"),
                credentials=credentials,
            )

            # Test query
            list(client.list_datasets(max_results=1))
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="BigQuery driver not installed", error="google-cloud-bigquery not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        from google.cloud import bigquery
        from google.oauth2 import service_account
        import json

        credentials_json = connection_data.get("credentials_json")
        if isinstance(credentials_json, str):
            credentials_info = json.loads(credentials_json)
        else:
            credentials_info = credentials_json

        credentials = service_account.Credentials.from_service_account_info(credentials_info)
        client = bigquery.Client(
            project=connection_data.get("project_id"),
            credentials=credentials,
        )

        tables = []
        dataset_id = connection_data.get("dataset")

        if dataset_id:
            dataset_ref = client.dataset(dataset_id)
            for table in client.list_tables(dataset_ref):
                tables.append({
                    "schema": dataset_id,
                    "name": table.table_id,
                    "type": table.table_type,
                })
        else:
            for dataset in client.list_datasets():
                for table in client.list_tables(dataset.dataset_id):
                    tables.append({
                        "schema": dataset.dataset_id,
                        "name": table.table_id,
                        "type": table.table_type,
                    })

        return tables

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        from google.cloud import bigquery
        from google.oauth2 import service_account
        import json

        credentials_json = connection_data.get("credentials_json")
        if isinstance(credentials_json, str):
            credentials_info = json.loads(credentials_json)
        else:
            credentials_info = credentials_json

        credentials = service_account.Credentials.from_service_account_info(credentials_info)
        client = bigquery.Client(
            project=connection_data.get("project_id"),
            credentials=credentials,
        )

        # Parse dataset.table
        if "." in table_name:
            dataset_id, table_id = table_name.split(".", 1)
        else:
            dataset_id = connection_data.get("dataset", "")
            table_id = table_name

        table_ref = client.dataset(dataset_id).table(table_id)
        table = client.get_table(table_ref)

        columns = [
            {
                "name": field.name,
                "type": field.field_type,
                "nullable": field.mode != "REQUIRED",
                "default": None,
            }
            for field in table.schema
        ]
        return columns


class RedshiftHandler(BaseDBHandler):
    """Amazon Redshift handler."""

    name = "redshift"
    type = "datawarehouse"
    title = "Amazon Redshift"
    description = "AWS data warehouse"
    icon = "redshift"
    connection_args = [
        ConnectionArg("host", "string", "Host", "Redshift cluster endpoint (e.g., my-cluster.xxxxx.region.redshift.amazonaws.com)", required=True),
        ConnectionArg("port", "integer", "Port", "Database port (default: 5439)", required=False, default=5439),
        ConnectionArg("user", "string", "User", "Database username", required=True),
        ConnectionArg("password", "password", "Password", "Database password", required=True, secret=True),
        ConnectionArg("database", "string", "Database", "Database name", required=True),
        ConnectionArg("ssl_mode", "string", "SSL Mode", "SSL connection mode (optional)", required=False, default="require"),
    ]

    @classmethod
    def is_available(cls) -> bool:
        # Redshift uses psycopg2 or redshift_connector
        try:
            import psycopg2
            return True
        except ImportError:
            try:
                import redshift_connector
                return True
            except ImportError:
                return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import psycopg2

            conn = psycopg2.connect(
                host=connection_data.get("host"),
                port=connection_data.get("port", 5439),
                dbname=connection_data.get("database"),
                user=connection_data.get("user") or connection_data.get("username"),
                password=connection_data.get("password"),
                sslmode=connection_data.get("ssl_mode", "require"),
                connect_timeout=10,
            )
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="Redshift driver not installed", error="psycopg2 not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Same as PostgreSQL
        return PostgresHandler.get_tables(connection_data)

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        return PostgresHandler.get_columns(connection_data, table_name)


class DatabricksHandler(BaseDBHandler):
    """Databricks handler using databricks-sql-connector."""

    name = "databricks"
    type = "datawarehouse"
    title = "Databricks"
    description = "Unified analytics platform"
    icon = "databricks"
    connection_args = [
        ConnectionArg("host", "string", "Host", "The server hostname for the cluster or SQL warehouse (e.g., adb-xxx.azuredatabricks.net)", required=True),
        ConnectionArg("auth_type", "select", "Authentication type", "Select authentication method", required=True, default="personal_access_token", options=[
            {"value": "personal_access_token", "label": "Personal Access Token"},
            {"value": "service_account", "label": "Service Account"},
        ]),
        ConnectionArg("http_path", "string", "HTTP Path", "The HTTP path of the cluster or SQL warehouse (e.g., /sql/1.0/warehouses/xxx)", required=True),
        # Personal Access Token auth
        ConnectionArg("access_token", "password", "Personal Access Token", "Databricks personal access token", required=True, secret=True, depends_on={"field": "auth_type", "values": ["personal_access_token"]}),
        # Service Account auth
        ConnectionArg("client_id", "string", "Client ID", "Service principal client ID", required=True, depends_on={"field": "auth_type", "values": ["service_account"]}),
        ConnectionArg("client_secret", "password", "Client Secret", "Service principal client secret", required=True, secret=True, depends_on={"field": "auth_type", "values": ["service_account"]}),
        # Common optional fields
        ConnectionArg("catalog", "string", "Catalog", "Catalog to use for the connection (optional)", required=False),
        ConnectionArg("schema", "string", "Schema", "Schema (database) to use for the connection (optional)", required=False),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            from databricks import sql
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            from databricks import sql

            conn = sql.connect(
                server_hostname=connection_data.get("host") or connection_data.get("server_hostname"),
                http_path=connection_data.get("http_path"),
                access_token=connection_data.get("password") or connection_data.get("access_token"),
                catalog=connection_data.get("catalog"),
                schema=connection_data.get("schema"),
            )
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="Databricks driver not installed", error="databricks-sql-connector not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        from databricks import sql

        conn = sql.connect(
            server_hostname=connection_data.get("host") or connection_data.get("server_hostname"),
            http_path=connection_data.get("http_path"),
            access_token=connection_data.get("password") or connection_data.get("access_token"),
            catalog=connection_data.get("catalog"),
            schema=connection_data.get("schema"),
        )
        try:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            tables = [
                {"schema": row[0] if len(row) > 1 else "", "name": row[1] if len(row) > 1 else row[0], "type": "TABLE"}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return tables
        finally:
            conn.close()

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        from databricks import sql

        conn = sql.connect(
            server_hostname=connection_data.get("host") or connection_data.get("server_hostname"),
            http_path=connection_data.get("http_path"),
            access_token=connection_data.get("password") or connection_data.get("access_token"),
            catalog=connection_data.get("catalog"),
            schema=connection_data.get("schema"),
        )
        try:
            cursor = conn.cursor()
            cursor.execute(f"DESCRIBE TABLE {table_name}")
            columns = [
                {"name": row[0], "type": row[1], "nullable": True, "default": None}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return columns
        finally:
            conn.close()


class OracleHandler(BaseDBHandler):
    """Oracle database handler using oracledb."""

    name = "oracle"
    type = "database"
    title = "Oracle"
    description = "Oracle Database"
    icon = "oracle"
    connection_args = [
        ConnectionArg("host", "string", "Host", "The hostname or IP address of the Oracle server", required=True),
        ConnectionArg("port", "integer", "Port", "The port number (default: 1521)", required=False, default=1521),
        ConnectionArg("user", "string", "Username", "The username for the Oracle database", required=True),
        ConnectionArg("password", "password", "Password", "The password for the Oracle database", required=True, secret=True),
        ConnectionArg("service_name", "string", "Service Name", "The service name of the Oracle database", required=False),
        ConnectionArg("sid", "string", "SID", "The system identifier (SID) of the Oracle database", required=False),
        ConnectionArg("dsn", "string", "DSN", "The data source name (alternative to host/port/sid)", required=False),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import oracledb
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import oracledb

            # Build connection params
            conn_params = {
                "user": connection_data.get("user"),
                "password": connection_data.get("password"),
            }

            if connection_data.get("dsn"):
                conn_params["dsn"] = connection_data["dsn"]
            else:
                conn_params["host"] = connection_data.get("host")
                conn_params["port"] = connection_data.get("port", 1521)
                if connection_data.get("service_name"):
                    conn_params["service_name"] = connection_data["service_name"]
                elif connection_data.get("sid"):
                    conn_params["sid"] = connection_data["sid"]

            conn = oracledb.connect(**conn_params)
            conn.ping()
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="Oracle driver not installed", error="oracledb not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        import oracledb

        conn_params = {
            "user": connection_data.get("user"),
            "password": connection_data.get("password"),
        }
        if connection_data.get("dsn"):
            conn_params["dsn"] = connection_data["dsn"]
        else:
            conn_params["host"] = connection_data.get("host")
            conn_params["port"] = connection_data.get("port", 1521)
            if connection_data.get("service_name"):
                conn_params["service_name"] = connection_data["service_name"]
            elif connection_data.get("sid"):
                conn_params["sid"] = connection_data["sid"]

        conn = oracledb.connect(**conn_params)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT OWNER, TABLE_NAME, 'TABLE' as TABLE_TYPE
                FROM ALL_TABLES
                WHERE OWNER NOT IN ('SYS', 'SYSTEM', 'OUTLN', 'DIP')
                ORDER BY OWNER, TABLE_NAME
            """)
            tables = [
                {"schema": row[0], "name": row[1], "type": row[2]}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return tables
        finally:
            conn.close()

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        import oracledb

        conn_params = {
            "user": connection_data.get("user"),
            "password": connection_data.get("password"),
        }
        if connection_data.get("dsn"):
            conn_params["dsn"] = connection_data["dsn"]
        else:
            conn_params["host"] = connection_data.get("host")
            conn_params["port"] = connection_data.get("port", 1521)
            if connection_data.get("service_name"):
                conn_params["service_name"] = connection_data["service_name"]
            elif connection_data.get("sid"):
                conn_params["sid"] = connection_data["sid"]

        conn = oracledb.connect(**conn_params)
        try:
            cursor = conn.cursor()
            # Parse schema.table if provided
            if "." in table_name:
                schema, table = table_name.split(".", 1)
            else:
                schema = connection_data.get("user", "").upper()
                table = table_name.upper()

            cursor.execute("""
                SELECT COLUMN_NAME, DATA_TYPE, NULLABLE, DATA_DEFAULT
                FROM ALL_TAB_COLUMNS
                WHERE OWNER = :schema AND TABLE_NAME = :table
                ORDER BY COLUMN_ID
            """, {"schema": schema, "table": table})

            columns = [
                {"name": row[0], "type": row[1], "nullable": row[2] == "Y", "default": row[3]}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return columns
        finally:
            conn.close()


class SAPHANAHandler(BaseDBHandler):
    """SAP HANA database handler using hdbcli."""

    name = "saphana"
    type = "database"
    title = "SAP HANA"
    description = "SAP HANA in-memory database"
    icon = "saphana"
    connection_args = [
        ConnectionArg("host", "string", "Host", "The hostname, IP address, or URL of the SAP HANA database", required=True),
        ConnectionArg("port", "integer", "Port", "The port number for connecting to SAP HANA", required=True),
        ConnectionArg("user", "string", "Username", "The username for the SAP HANA database", required=True),
        ConnectionArg("password", "password", "Password", "The password for the SAP HANA database", required=True, secret=True),
        ConnectionArg("database", "string", "Database", "The name of the database to connect to", required=False),
        ConnectionArg("schema", "string", "Schema", "The database schema to use", required=False),
        ConnectionArg("encrypt", "boolean", "Encrypt", "Enable/disable encryption (default: True)", required=False, default=True),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            from hdbcli import dbapi
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            from hdbcli import dbapi

            conn_params = {
                "address": connection_data.get("host"),
                "port": connection_data.get("port"),
                "user": connection_data.get("user"),
                "password": connection_data.get("password"),
            }
            if connection_data.get("database"):
                conn_params["databaseName"] = connection_data["database"]
            if connection_data.get("schema"):
                conn_params["currentSchema"] = connection_data["schema"]
            if connection_data.get("encrypt") is not None:
                conn_params["encrypt"] = connection_data["encrypt"]

            conn = dbapi.connect(**conn_params)
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM SYS.DUMMY")
            cursor.close()
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="SAP HANA driver not installed", error="hdbcli not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        from hdbcli import dbapi

        conn_params = {
            "address": connection_data.get("host"),
            "port": connection_data.get("port"),
            "user": connection_data.get("user"),
            "password": connection_data.get("password"),
        }
        if connection_data.get("database"):
            conn_params["databaseName"] = connection_data["database"]
        if connection_data.get("schema"):
            conn_params["currentSchema"] = connection_data["schema"]

        conn = dbapi.connect(**conn_params)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT SCHEMA_NAME, TABLE_NAME, TABLE_TYPE
                FROM SYS.TABLES
                WHERE SCHEMA_NAME NOT LIKE 'SYS%' AND SCHEMA_NAME NOT LIKE '_SYS%'
                ORDER BY SCHEMA_NAME, TABLE_NAME
            """)
            tables = [
                {"schema": row[0], "name": row[1], "type": row[2]}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return tables
        finally:
            conn.close()

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        from hdbcli import dbapi

        conn_params = {
            "address": connection_data.get("host"),
            "port": connection_data.get("port"),
            "user": connection_data.get("user"),
            "password": connection_data.get("password"),
        }
        if connection_data.get("database"):
            conn_params["databaseName"] = connection_data["database"]

        conn = dbapi.connect(**conn_params)
        try:
            cursor = conn.cursor()
            if "." in table_name:
                schema, table = table_name.split(".", 1)
            else:
                schema = connection_data.get("schema", connection_data.get("user", "").upper())
                table = table_name

            cursor.execute("""
                SELECT COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE, DEFAULT_VALUE
                FROM SYS.TABLE_COLUMNS
                WHERE SCHEMA_NAME = ? AND TABLE_NAME = ?
                ORDER BY POSITION
            """, (schema, table))

            columns = [
                {"name": row[0], "type": row[1], "nullable": row[2] == "TRUE", "default": row[3]}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return columns
        finally:
            conn.close()


class AthenaHandler(BaseDBHandler):
    """Amazon Athena handler using boto3."""

    name = "athena"
    type = "queryengine"
    title = "Amazon Athena"
    description = "AWS serverless query service"
    icon = "athena"
    connection_args = [
        ConnectionArg("region_name", "string", "Region", "The AWS region where the Athena tables are created", required=True),
        ConnectionArg("aws_access_key_id", "string", "Access key", "The access key for the AWS account", required=True),
        ConnectionArg("aws_secret_access_key", "password", "Secret key", "The secret key for the AWS account", required=True, secret=True),
        ConnectionArg("results_output_location", "string", "S3 output location", "S3 location for query results (s3://bucket-path/)", required=True),
        ConnectionArg("database", "string", "Datasource (Optional)", "The name of the Athena database/datasource", required=False),
        ConnectionArg("endpoint_vpc", "string", "Endpoint VPC (Optional)", "VPC endpoint for Athena", required=False),
        ConnectionArg("workgroup", "string", "Workgroup", "The Athena Workgroup (optional)", required=False),
        ConnectionArg("catalog", "string", "Catalog", "The AWS Data Catalog (default: AwsDataCatalog)", required=False, default="AwsDataCatalog"),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import boto3
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import boto3
            import time

            # Build client config with optional endpoint
            client_config = {
                "aws_access_key_id": connection_data.get("aws_access_key_id"),
                "aws_secret_access_key": connection_data.get("aws_secret_access_key"),
                "region_name": connection_data.get("region_name"),
            }
            endpoint_vpc = connection_data.get("endpoint_vpc")
            if endpoint_vpc:
                client_config["endpoint_url"] = endpoint_vpc

            client = boto3.client("athena", **client_config)

            # Build query execution params
            query_params = {
                "QueryString": "SELECT 1",
                "ResultConfiguration": {
                    "OutputLocation": connection_data.get("results_output_location"),
                },
            }

            # Add optional query context
            database = connection_data.get("database")
            catalog = connection_data.get("catalog", "AwsDataCatalog")
            if database:
                query_params["QueryExecutionContext"] = {
                    "Database": database,
                    "Catalog": catalog,
                }

            # Add optional workgroup
            workgroup = connection_data.get("workgroup")
            if workgroup:
                query_params["WorkGroup"] = workgroup

            response = client.start_query_execution(**query_params)

            query_execution_id = response["QueryExecutionId"]

            # Wait for query to complete (with timeout)
            for _ in range(30):  # 30 second timeout
                result = client.get_query_execution(QueryExecutionId=query_execution_id)
                state = result["QueryExecution"]["Status"]["State"]
                if state in ["SUCCEEDED", "FAILED", "CANCELLED"]:
                    break
                time.sleep(1)

            if state == "SUCCEEDED":
                return ConnectionTestResult(success=True, message="Connection successful")
            else:
                error_msg = result["QueryExecution"]["Status"].get("StateChangeReason", "Query failed")
                return ConnectionTestResult(success=False, message=f"Query failed: {error_msg}", error=error_msg)

        except ImportError:
            return ConnectionTestResult(success=False, message="Athena driver not installed", error="boto3 not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        import boto3

        glue = boto3.client(
            "glue",
            aws_access_key_id=connection_data.get("aws_access_key_id"),
            aws_secret_access_key=connection_data.get("aws_secret_access_key"),
            region_name=connection_data.get("region_name"),
        )

        database = connection_data.get("database")
        tables = []

        paginator = glue.get_paginator("get_tables")
        for page in paginator.paginate(DatabaseName=database):
            for table in page["TableList"]:
                tables.append({
                    "schema": database,
                    "name": table["Name"],
                    "type": table.get("TableType", "TABLE"),
                })

        return tables

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        import boto3

        glue = boto3.client(
            "glue",
            aws_access_key_id=connection_data.get("aws_access_key_id"),
            aws_secret_access_key=connection_data.get("aws_secret_access_key"),
            region_name=connection_data.get("region_name"),
        )

        database = connection_data.get("database")
        response = glue.get_table(DatabaseName=database, Name=table_name)

        columns = []
        for col in response["Table"].get("StorageDescriptor", {}).get("Columns", []):
            columns.append({
                "name": col["Name"],
                "type": col["Type"],
                "nullable": True,
                "default": None,
            })
        # Add partition columns
        for col in response["Table"].get("PartitionKeys", []):
            columns.append({
                "name": col["Name"],
                "type": col["Type"],
                "nullable": True,
                "default": None,
            })

        return columns


class TrinoHandler(BaseDBHandler):
    """Trino (formerly Presto SQL) handler."""

    name = "trino"
    type = "queryengine"
    title = "Trino"
    description = "Distributed SQL query engine"
    icon = "trino"
    connection_args = [
        ConnectionArg("host", "string", "Host", "The hostname or IP address of the Trino server", required=True),
        ConnectionArg("port", "integer", "Port", "The port number for Trino (default: 8080)", required=False, default=8080),
        ConnectionArg("user", "string", "Username", "The username for authentication", required=True),
        ConnectionArg("password", "password", "Password", "The password for authentication", required=False, secret=True),
        ConnectionArg("catalog", "string", "Catalog", "The Trino catalog to use", required=True),
        ConnectionArg("schema", "string", "Schema", "The Trino schema to use", required=False),
        ConnectionArg("http_scheme", "string", "HTTP Scheme", "HTTP scheme (http or https)", required=False, default="http"),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            from trino.dbapi import connect
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            from trino.dbapi import connect
            from trino.auth import BasicAuthentication

            auth = None
            if connection_data.get("password"):
                auth = BasicAuthentication(
                    connection_data.get("user"),
                    connection_data.get("password"),
                )

            conn = connect(
                host=connection_data.get("host"),
                port=connection_data.get("port", 8080),
                user=connection_data.get("user"),
                catalog=connection_data.get("catalog"),
                schema=connection_data.get("schema"),
                http_scheme=connection_data.get("http_scheme", "http"),
                auth=auth,
            )
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="Trino driver not installed", error="trino not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        from trino.dbapi import connect
        from trino.auth import BasicAuthentication

        auth = None
        if connection_data.get("password"):
            auth = BasicAuthentication(
                connection_data.get("user"),
                connection_data.get("password"),
            )

        conn = connect(
            host=connection_data.get("host"),
            port=connection_data.get("port", 8080),
            user=connection_data.get("user"),
            catalog=connection_data.get("catalog"),
            schema=connection_data.get("schema"),
            http_scheme=connection_data.get("http_scheme", "http"),
            auth=auth,
        )
        try:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            tables = [
                {"schema": connection_data.get("schema", ""), "name": row[0], "type": "TABLE"}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return tables
        finally:
            conn.close()

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        from trino.dbapi import connect
        from trino.auth import BasicAuthentication

        auth = None
        if connection_data.get("password"):
            auth = BasicAuthentication(
                connection_data.get("user"),
                connection_data.get("password"),
            )

        conn = connect(
            host=connection_data.get("host"),
            port=connection_data.get("port", 8080),
            user=connection_data.get("user"),
            catalog=connection_data.get("catalog"),
            schema=connection_data.get("schema"),
            http_scheme=connection_data.get("http_scheme", "http"),
            auth=auth,
        )
        try:
            cursor = conn.cursor()
            cursor.execute(f"DESCRIBE {table_name}")
            columns = [
                {"name": row[0], "type": row[1], "nullable": True, "default": None}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return columns
        finally:
            conn.close()


class PrestoHandler(BaseDBHandler):
    """Presto handler (uses same driver as Trino)."""

    name = "presto"
    type = "queryengine"
    title = "Presto"
    description = "Distributed SQL query engine"
    icon = "presto"
    connection_args = [
        ConnectionArg("host", "string", "Host", "The hostname or IP address of the Presto server", required=True),
        ConnectionArg("port", "integer", "Port", "The port number for Presto (default: 8080)", required=False, default=8080),
        ConnectionArg("user", "string", "Username", "The username for authentication", required=True),
        ConnectionArg("password", "password", "Password", "The password for authentication", required=False, secret=True),
        ConnectionArg("catalog", "string", "Catalog", "The Presto catalog to use", required=True),
        ConnectionArg("schema", "string", "Schema", "The Presto schema to use", required=False),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            from pyhive import presto
            return True
        except ImportError:
            try:
                from trino.dbapi import connect
                return True
            except ImportError:
                return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            from pyhive import presto

            conn = presto.connect(
                host=connection_data.get("host"),
                port=connection_data.get("port", 8080),
                username=connection_data.get("user"),
                catalog=connection_data.get("catalog"),
                schema=connection_data.get("schema"),
            )
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="Presto driver not installed", error="pyhive not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        from pyhive import presto

        conn = presto.connect(
            host=connection_data.get("host"),
            port=connection_data.get("port", 8080),
            username=connection_data.get("user"),
            catalog=connection_data.get("catalog"),
            schema=connection_data.get("schema"),
        )
        try:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES")
            tables = [
                {"schema": connection_data.get("schema", ""), "name": row[0], "type": "TABLE"}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return tables
        finally:
            conn.close()

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        from pyhive import presto

        conn = presto.connect(
            host=connection_data.get("host"),
            port=connection_data.get("port", 8080),
            username=connection_data.get("user"),
            catalog=connection_data.get("catalog"),
            schema=connection_data.get("schema"),
        )
        try:
            cursor = conn.cursor()
            cursor.execute(f"DESCRIBE {table_name}")
            columns = [
                {"name": row[0], "type": row[1], "nullable": True, "default": None}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return columns
        finally:
            conn.close()


class DremioHandler(BaseDBHandler):
    """Dremio handler using Arrow Flight or REST API."""

    name = "dremio"
    type = "queryengine"
    title = "Dremio"
    description = "Data lake engine"
    icon = "dremio"
    connection_args = [
        ConnectionArg("host", "string", "Host", "The hostname or IP address of the Dremio server", required=True),
        ConnectionArg("port", "integer", "Port", "The port that Dremio is running on (default: 9047)", required=False, default=9047),
        ConnectionArg("username", "string", "Username", "The username for Dremio", required=True),
        ConnectionArg("password", "password", "Password", "The password for Dremio", required=True, secret=True),
        ConnectionArg("ssl", "boolean", "Use SSL", "Use HTTPS for connection", required=False, default=False),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import requests
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import requests
            import json

            host = connection_data.get("host")
            port = connection_data.get("port", 9047)
            ssl = connection_data.get("ssl", False)
            protocol = "https" if ssl else "http"

            headers = {"Content-Type": "application/json"}
            data = json.dumps({
                "userName": connection_data.get("username"),
                "password": connection_data.get("password"),
            })

            response = requests.post(
                f"{protocol}://{host}:{port}/apiv2/login",
                headers=headers,
                data=data,
                timeout=10,
                verify=False if ssl else True,
            )

            if response.status_code == 200:
                return ConnectionTestResult(success=True, message="Connection successful")
            else:
                return ConnectionTestResult(
                    success=False,
                    message=f"Authentication failed: {response.status_code}",
                    error=response.text
                )
        except ImportError:
            return ConnectionTestResult(success=False, message="HTTP library not available", error="requests not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Dremio uses a catalog-based structure via REST API
        return []

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        return []


class TeradataHandler(BaseDBHandler):
    """Teradata database handler using teradatasql."""

    name = "teradata"
    type = "database"
    title = "Teradata"
    description = "Teradata database"
    icon = "teradata"
    connection_args = [
        ConnectionArg("host", "string", "Host", "The hostname or IP address of the Teradata server", required=True),
        ConnectionArg("user", "string", "Username", "The username for Teradata", required=True),
        ConnectionArg("password", "password", "Password", "The password for Teradata", required=True, secret=True),
        ConnectionArg("database", "string", "Database", "The name of the database to connect to", required=False),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import teradatasql
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import teradatasql

            conn_params = {
                "host": connection_data.get("host"),
                "user": connection_data.get("user"),
                "password": connection_data.get("password"),
            }
            if connection_data.get("database"):
                conn_params["database"] = connection_data["database"]

            conn = teradatasql.connect(**conn_params)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="Teradata driver not installed", error="teradatasql not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        import teradatasql

        conn_params = {
            "host": connection_data.get("host"),
            "user": connection_data.get("user"),
            "password": connection_data.get("password"),
        }
        if connection_data.get("database"):
            conn_params["database"] = connection_data["database"]

        conn = teradatasql.connect(**conn_params)
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DatabaseName, TableName, TableKind
                FROM DBC.TablesV
                WHERE TableKind IN ('T', 'V')
                ORDER BY DatabaseName, TableName
            """)
            tables = [
                {"schema": row[0], "name": row[1], "type": "TABLE" if row[2] == "T" else "VIEW"}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return tables
        finally:
            conn.close()

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        import teradatasql

        conn_params = {
            "host": connection_data.get("host"),
            "user": connection_data.get("user"),
            "password": connection_data.get("password"),
        }
        if connection_data.get("database"):
            conn_params["database"] = connection_data["database"]

        conn = teradatasql.connect(**conn_params)
        try:
            cursor = conn.cursor()
            if "." in table_name:
                database, table = table_name.split(".", 1)
            else:
                database = connection_data.get("database", "")
                table = table_name

            cursor.execute("""
                SELECT ColumnName, ColumnType, Nullable, DefaultValue
                FROM DBC.ColumnsV
                WHERE DatabaseName = ? AND TableName = ?
                ORDER BY ColumnId
            """, (database, table))

            columns = [
                {"name": row[0], "type": row[1], "nullable": row[2] == "Y", "default": row[3]}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return columns
        finally:
            conn.close()


class SingleStoreHandler(BaseDBHandler):
    """SingleStore (formerly MemSQL) handler - uses MySQL protocol."""

    name = "singlestore"
    type = "database"
    title = "SingleStore"
    description = "SingleStore distributed database"
    icon = "singlestore"
    connection_args = [
        ConnectionArg("host", "string", "Host", "Database server hostname", required=True),
        ConnectionArg("port", "integer", "Port", "Database port (default: 3306)", required=False, default=3306),
        ConnectionArg("database", "string", "Database", "Database name", required=True),
        ConnectionArg("user", "string", "Username", "Database username", required=True),
        ConnectionArg("password", "password", "Password", "Database password", required=True, secret=True),
        ConnectionArg("ssl", "boolean", "Use SSL", "Enable SSL connection", required=False, default=False),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import mysql.connector
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        # SingleStore is MySQL-compatible
        return MySQLHandler.test_connection(connection_data)

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        return MySQLHandler.get_tables(connection_data)

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        return MySQLHandler.get_columns(connection_data, table_name)


class AzureSynapseHandler(BaseDBHandler):
    """Azure Synapse Analytics handler - uses SQL Server protocol."""

    name = "azuresynapse"
    type = "datawarehouse"
    title = "Azure Synapse"
    description = "Azure Synapse Analytics"
    icon = "azuresynapse"
    connection_args = [
        ConnectionArg("host", "string", "Host", "Azure Synapse server name (e.g., yourserver.sql.azuresynapse.net)", required=True),
        ConnectionArg("port", "integer", "Port", "Database port (default: 1433)", required=False, default=1433),
        ConnectionArg("user", "string", "User", "Database username", required=True),
        ConnectionArg("password", "password", "Password", "Database password", required=True, secret=True),
        ConnectionArg("database", "string", "Database", "Database name", required=True),
        ConnectionArg("encrypt", "boolean", "Encrypt", "Enable encryption (default: True)", required=False, default=True),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import pyodbc
            return True
        except ImportError:
            try:
                import pymssql
                return True
            except ImportError:
                return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import pyodbc

            host = connection_data.get("host")
            port = connection_data.get("port", 1433)
            database = connection_data.get("database")
            user = connection_data.get("user")
            password = connection_data.get("password")
            encrypt = "yes" if connection_data.get("encrypt", True) else "no"

            conn_str = (
                f"DRIVER={{ODBC Driver 18 for SQL Server}};"
                f"SERVER={host},{port};"
                f"DATABASE={database};"
                f"UID={user};"
                f"PWD={password};"
                f"Encrypt={encrypt};"
                f"TrustServerCertificate=yes;"
            )

            conn = pyodbc.connect(conn_str, timeout=10)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            # Fallback to pymssql
            try:
                return SQLServerHandler.test_connection(connection_data)
            except:
                return ConnectionTestResult(success=False, message="Azure Synapse driver not installed", error="pyodbc or pymssql not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        return SQLServerHandler.get_tables(connection_data)

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        return SQLServerHandler.get_columns(connection_data, table_name)


class StarburstHandler(BaseDBHandler):
    """Starburst handler - Trino-compatible."""

    name = "starburst"
    type = "queryengine"
    title = "Starburst"
    description = "Starburst Enterprise/Galaxy"
    icon = "starburst"
    connection_args = [
        ConnectionArg("host", "string", "Host", "The hostname of the Starburst cluster", required=True),
        ConnectionArg("port", "integer", "Port", "The port number (default: 443)", required=False, default=443),
        ConnectionArg("user", "string", "Username", "The username for authentication", required=True),
        ConnectionArg("password", "password", "Password", "The password for authentication", required=True, secret=True),
        ConnectionArg("catalog", "string", "Catalog", "The catalog to use", required=True),
        ConnectionArg("schema", "string", "Schema", "The schema to use", required=False),
    ]

    @classmethod
    def is_available(cls) -> bool:
        return TrinoHandler.is_available()

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        # Starburst uses Trino protocol with HTTPS
        modified_data = {**connection_data, "http_scheme": "https"}
        return TrinoHandler.test_connection(modified_data)

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        modified_data = {**connection_data, "http_scheme": "https"}
        return TrinoHandler.get_tables(modified_data)

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        modified_data = {**connection_data, "http_scheme": "https"}
        return TrinoHandler.get_columns(modified_data, table_name)


class MariaDBHandler(BaseDBHandler):
    """MariaDB handler - MySQL compatible."""

    name = "mariadb"
    type = "database"
    title = "MariaDB"
    description = "MariaDB database"
    icon = "mariadb"
    connection_args = MySQLHandler.connection_args

    @classmethod
    def is_available(cls) -> bool:
        return MySQLHandler.is_available()

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        return MySQLHandler.test_connection(connection_data)

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        return MySQLHandler.get_tables(connection_data)

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        return MySQLHandler.get_columns(connection_data, table_name)


class CockroachDBHandler(BaseDBHandler):
    """CockroachDB handler - PostgreSQL compatible."""

    name = "cockroachdb"
    type = "database"
    title = "CockroachDB"
    description = "CockroachDB distributed database"
    icon = "cockroachdb"
    connection_args = PostgresHandler.connection_args

    @classmethod
    def is_available(cls) -> bool:
        return PostgresHandler.is_available()

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        return PostgresHandler.test_connection(connection_data)

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        return PostgresHandler.get_tables(connection_data)

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        return PostgresHandler.get_columns(connection_data, table_name)


class ClickHouseHandler(BaseDBHandler):
    """ClickHouse handler."""

    name = "clickhouse"
    type = "database"
    title = "ClickHouse"
    description = "ClickHouse analytics database"
    icon = "clickhouse"
    connection_args = [
        ConnectionArg("host", "string", "Host", "Database server hostname", required=True),
        ConnectionArg("port", "integer", "Port", "Database port (default: 9000)", required=False, default=9000),
        ConnectionArg("database", "string", "Database", "Database name", required=True),
        ConnectionArg("user", "string", "Username", "Database username", required=True),
        ConnectionArg("password", "password", "Password", "Database password", required=False, secret=True),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import clickhouse_driver
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            from clickhouse_driver import Client

            client = Client(
                host=connection_data.get("host"),
                port=connection_data.get("port", 9000),
                database=connection_data.get("database"),
                user=connection_data.get("user"),
                password=connection_data.get("password", ""),
            )
            client.execute("SELECT 1")
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="ClickHouse driver not installed", error="clickhouse-driver not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        from clickhouse_driver import Client

        client = Client(
            host=connection_data.get("host"),
            port=connection_data.get("port", 9000),
            database=connection_data.get("database"),
            user=connection_data.get("user"),
            password=connection_data.get("password", ""),
        )

        result = client.execute("SHOW TABLES")
        tables = [
            {"schema": connection_data.get("database"), "name": row[0], "type": "TABLE"}
            for row in result
        ]
        return tables

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        from clickhouse_driver import Client

        client = Client(
            host=connection_data.get("host"),
            port=connection_data.get("port", 9000),
            database=connection_data.get("database"),
            user=connection_data.get("user"),
            password=connection_data.get("password", ""),
        )

        result = client.execute(f"DESCRIBE TABLE {table_name}")
        columns = [
            {"name": row[0], "type": row[1], "nullable": "Nullable" in row[1], "default": row[3] if len(row) > 3 else None}
            for row in result
        ]
        return columns


# ============================================================
# FILE-BASED DATA SOURCES
# ============================================================


class CSVFileHandler(BaseDBHandler):
    """CSV File handler using pandas."""

    name = "csv"
    type = "file"
    title = "CSV File"
    description = "Connect to CSV files via URL or file upload"
    icon = "csv"
    connection_args = [
        ConnectionArg("file_url", "string", "File URL", "URL to the CSV file (S3, HTTP, or local path)", required=True),
        ConnectionArg("delimiter", "string", "Delimiter", "Column delimiter (default: comma)", required=False, default=","),
        ConnectionArg("encoding", "string", "Encoding", "File encoding (default: utf-8)", required=False, default="utf-8"),
        ConnectionArg("header_row", "integer", "Header Row", "Row number containing headers (0-indexed, default: 0)", required=False, default=0),
        ConnectionArg("aws_access_key_id", "string", "AWS Access Key ID", "AWS access key for S3 files (optional)", required=False),
        ConnectionArg("aws_secret_access_key", "password", "AWS Secret Access Key", "AWS secret key for S3 files (optional)", required=False, secret=True),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import pandas
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import pandas as pd

            file_url = connection_data.get("file_url", "")
            delimiter = connection_data.get("delimiter", ",")
            encoding = connection_data.get("encoding", "utf-8")
            header_row = connection_data.get("header_row", 0)

            storage_options = None
            if file_url.startswith("s3://"):
                aws_key = connection_data.get("aws_access_key_id")
                aws_secret = connection_data.get("aws_secret_access_key")
                if aws_key and aws_secret:
                    storage_options = {
                        "key": aws_key,
                        "secret": aws_secret,
                    }

            # Try to read first few rows to validate
            df = pd.read_csv(
                file_url,
                sep=delimiter,
                encoding=encoding,
                header=header_row,
                nrows=5,
                storage_options=storage_options,
            )

            if df.empty:
                return ConnectionTestResult(success=False, message="CSV file is empty", error="No data found")

            return ConnectionTestResult(
                success=True,
                message=f"Connection successful. Found {len(df.columns)} columns."
            )
        except ImportError:
            return ConnectionTestResult(success=False, message="pandas not installed", error="pandas not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Failed to read CSV: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        # CSV files are single-table, use file name as table name
        file_url = connection_data.get("file_url", "")
        file_name = file_url.split("/")[-1].split("?")[0]  # Extract filename
        if file_name.endswith(".csv"):
            file_name = file_name[:-4]
        return [{"schema": "file", "name": file_name or "csv_data", "type": "FILE"}]

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        import pandas as pd

        file_url = connection_data.get("file_url", "")
        delimiter = connection_data.get("delimiter", ",")
        encoding = connection_data.get("encoding", "utf-8")
        header_row = connection_data.get("header_row", 0)

        storage_options = None
        if file_url.startswith("s3://"):
            aws_key = connection_data.get("aws_access_key_id")
            aws_secret = connection_data.get("aws_secret_access_key")
            if aws_key and aws_secret:
                storage_options = {
                    "key": aws_key,
                    "secret": aws_secret,
                }

        df = pd.read_csv(
            file_url,
            sep=delimiter,
            encoding=encoding,
            header=header_row,
            nrows=100,  # Read sample to infer types
            storage_options=storage_options,
        )

        columns = []
        for col_name, dtype in df.dtypes.items():
            columns.append({
                "name": str(col_name),
                "type": str(dtype),
                "nullable": df[col_name].isnull().any(),
                "default": None,
            })
        return columns


class GoogleSheetsHandler(BaseDBHandler):
    """Google Sheets handler using gspread."""

    name = "google_sheets"
    type = "file"
    title = "Google Sheets"
    description = "Connect to Google Sheets spreadsheets"
    icon = "googlesheets"
    connection_args = [
        ConnectionArg("spreadsheet_id", "string", "Spreadsheet ID", "The ID of the Google Sheet (from URL)", required=True),
        ConnectionArg("credentials_json", "text", "Service Account JSON", "Google Cloud service account credentials JSON", required=True, secret=True),
        ConnectionArg("worksheet_name", "string", "Worksheet Name", "Name of the specific worksheet (default: first sheet)", required=False),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            return True
        except ImportError:
            return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            import json

            credentials_json = connection_data.get("credentials_json")
            if isinstance(credentials_json, str):
                credentials_info = json.loads(credentials_json)
            else:
                credentials_info = credentials_json

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets.readonly",
                "https://www.googleapis.com/auth/drive.readonly",
            ]
            credentials = Credentials.from_service_account_info(credentials_info, scopes=scopes)
            client = gspread.authorize(credentials)

            spreadsheet_id = connection_data.get("spreadsheet_id")
            spreadsheet = client.open_by_key(spreadsheet_id)

            worksheet_name = connection_data.get("worksheet_name")
            if worksheet_name:
                worksheet = spreadsheet.worksheet(worksheet_name)
            else:
                worksheet = spreadsheet.sheet1

            # Try to read a few rows
            records = worksheet.get_all_values()[:5]

            return ConnectionTestResult(
                success=True,
                message=f"Connection successful. Spreadsheet: {spreadsheet.title}"
            )
        except ImportError:
            return ConnectionTestResult(success=False, message="gspread not installed", error="gspread not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Failed to connect: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        import gspread
        from google.oauth2.service_account import Credentials
        import json

        credentials_json = connection_data.get("credentials_json")
        if isinstance(credentials_json, str):
            credentials_info = json.loads(credentials_json)
        else:
            credentials_info = credentials_json

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        credentials = Credentials.from_service_account_info(credentials_info, scopes=scopes)
        client = gspread.authorize(credentials)

        spreadsheet_id = connection_data.get("spreadsheet_id")
        spreadsheet = client.open_by_key(spreadsheet_id)

        # Each worksheet is a "table"
        tables = []
        for worksheet in spreadsheet.worksheets():
            tables.append({
                "schema": spreadsheet.title,
                "name": worksheet.title,
                "type": "SHEET",
            })
        return tables

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        import gspread
        from google.oauth2.service_account import Credentials
        import json

        credentials_json = connection_data.get("credentials_json")
        if isinstance(credentials_json, str):
            credentials_info = json.loads(credentials_json)
        else:
            credentials_info = credentials_json

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        credentials = Credentials.from_service_account_info(credentials_info, scopes=scopes)
        client = gspread.authorize(credentials)

        spreadsheet_id = connection_data.get("spreadsheet_id")
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(table_name)

        # First row is headers
        headers = worksheet.row_values(1)
        columns = [
            {"name": header, "type": "string", "nullable": True, "default": None}
            for header in headers if header
        ]
        return columns


# ============================================================
# OTHER DATA SOURCES
# ============================================================


class LookerHandler(BaseDBHandler):
    """Looker handler using Looker SDK."""

    name = "looker"
    type = "other"
    title = "Looker"
    description = "Connect to Looker for analytics and BI data"
    icon = "looker"
    connection_args = [
        ConnectionArg("base_url", "string", "Looker URL", "Base URL of your Looker instance (e.g., https://company.looker.com)", required=True),
        ConnectionArg("client_id", "string", "Client ID", "API3 Client ID from Looker", required=True),
        ConnectionArg("client_secret", "password", "Client Secret", "API3 Client Secret from Looker", required=True, secret=True),
        ConnectionArg("verify_ssl", "boolean", "Verify SSL", "Verify SSL certificates (default: True)", required=False, default=True),
    ]

    @classmethod
    def is_available(cls) -> bool:
        try:
            import looker_sdk
            return True
        except ImportError:
            # Fallback to requests
            try:
                import requests
                return True
            except ImportError:
                return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import requests

            base_url = connection_data.get("base_url", "").rstrip("/")
            client_id = connection_data.get("client_id")
            client_secret = connection_data.get("client_secret")
            verify_ssl = connection_data.get("verify_ssl", True)

            # Authenticate using API3 credentials
            auth_url = f"{base_url}/api/4.0/login"
            response = requests.post(
                auth_url,
                data={"client_id": client_id, "client_secret": client_secret},
                verify=verify_ssl,
                timeout=10,
            )

            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get("access_token")

                # Test the token by getting current user
                me_url = f"{base_url}/api/4.0/user"
                me_response = requests.get(
                    me_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    verify=verify_ssl,
                    timeout=10,
                )

                if me_response.status_code == 200:
                    user = me_response.json()
                    return ConnectionTestResult(
                        success=True,
                        message=f"Connection successful. Logged in as: {user.get('display_name', 'Unknown')}"
                    )
                else:
                    return ConnectionTestResult(
                        success=False,
                        message=f"Authentication succeeded but API test failed: {me_response.status_code}",
                        error=me_response.text
                    )
            else:
                return ConnectionTestResult(
                    success=False,
                    message=f"Authentication failed: {response.status_code}",
                    error=response.text
                )

        except ImportError:
            return ConnectionTestResult(success=False, message="requests library not installed", error="requests not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get Looker explores/views as tables."""
        import requests

        base_url = connection_data.get("base_url", "").rstrip("/")
        client_id = connection_data.get("client_id")
        client_secret = connection_data.get("client_secret")
        verify_ssl = connection_data.get("verify_ssl", True)

        # Authenticate
        auth_url = f"{base_url}/api/4.0/login"
        response = requests.post(
            auth_url,
            data={"client_id": client_id, "client_secret": client_secret},
            verify=verify_ssl,
            timeout=10,
        )

        if response.status_code != 200:
            return []

        access_token = response.json().get("access_token")
        headers = {"Authorization": f"Bearer {access_token}"}

        # Get all LookML models and their explores
        models_url = f"{base_url}/api/4.0/lookml_models"
        models_response = requests.get(models_url, headers=headers, verify=verify_ssl, timeout=30)

        tables = []
        if models_response.status_code == 200:
            models = models_response.json()
            for model in models:
                model_name = model.get("name", "")
                for explore in model.get("explores", []):
                    tables.append({
                        "schema": model_name,
                        "name": explore.get("name", ""),
                        "type": "EXPLORE",
                    })

        return tables

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        """Get fields from a Looker explore."""
        import requests

        base_url = connection_data.get("base_url", "").rstrip("/")
        client_id = connection_data.get("client_id")
        client_secret = connection_data.get("client_secret")
        verify_ssl = connection_data.get("verify_ssl", True)

        # Authenticate
        auth_url = f"{base_url}/api/4.0/login"
        response = requests.post(
            auth_url,
            data={"client_id": client_id, "client_secret": client_secret},
            verify=verify_ssl,
            timeout=10,
        )

        if response.status_code != 200:
            return []

        access_token = response.json().get("access_token")
        headers = {"Authorization": f"Bearer {access_token}"}

        # Parse model_name.explore_name format
        if "." in table_name:
            model_name, explore_name = table_name.split(".", 1)
        else:
            # Try to find the explore in any model
            return []

        # Get explore details
        explore_url = f"{base_url}/api/4.0/lookml_models/{model_name}/explores/{explore_name}"
        explore_response = requests.get(explore_url, headers=headers, verify=verify_ssl, timeout=30)

        columns = []
        if explore_response.status_code == 200:
            explore = explore_response.json()
            # Get dimensions
            for field in explore.get("fields", {}).get("dimensions", []):
                columns.append({
                    "name": field.get("name", ""),
                    "type": field.get("type", "string"),
                    "nullable": True,
                    "default": None,
                })
            # Get measures
            for field in explore.get("fields", {}).get("measures", []):
                columns.append({
                    "name": field.get("name", ""),
                    "type": field.get("type", "number"),
                    "nullable": True,
                    "default": None,
                })

        return columns


class DenodoHandler(BaseDBHandler):
    """Denodo handler using JDBC/ODBC via pyodbc or jaydebeapi."""

    name = "denodo"
    type = "other"
    title = "Denodo"
    description = "Connect to Denodo data virtualization platform"
    icon = "denodo"
    connection_args = [
        ConnectionArg("host", "string", "Host", "Denodo server hostname", required=True),
        ConnectionArg("port", "integer", "Port", "Denodo port (default: 9999)", required=False, default=9999),
        ConnectionArg("database", "string", "Database", "Virtual database name", required=True),
        ConnectionArg("username", "string", "Username", "Denodo username", required=True),
        ConnectionArg("password", "password", "Password", "Denodo password", required=True, secret=True),
        ConnectionArg("ssl", "boolean", "Use SSL", "Use SSL connection", required=False, default=False),
    ]

    @classmethod
    def is_available(cls) -> bool:
        # Denodo can work via ODBC or JDBC
        try:
            import pyodbc
            return True
        except ImportError:
            try:
                import jaydebeapi
                return True
            except ImportError:
                return False

    @classmethod
    def test_connection(cls, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        try:
            import pyodbc

            host = connection_data.get("host")
            port = connection_data.get("port", 9999)
            database = connection_data.get("database")
            username = connection_data.get("username")
            password = connection_data.get("password")
            ssl = connection_data.get("ssl", False)

            # Denodo ODBC connection string
            conn_str = (
                f"DRIVER={{DenodoODBC Unicode}};"
                f"SERVER={host};"
                f"PORT={port};"
                f"DATABASE={database};"
                f"UID={username};"
                f"PWD={password};"
            )
            if ssl:
                conn_str += "SSL=true;"

            conn = pyodbc.connect(conn_str, timeout=10)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            return ConnectionTestResult(success=True, message="Connection successful")
        except ImportError:
            return ConnectionTestResult(success=False, message="Denodo driver not installed", error="pyodbc with Denodo driver not available")
        except Exception as e:
            return ConnectionTestResult(success=False, message=f"Connection failed: {str(e)}", error=str(e))

    @classmethod
    def get_tables(cls, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        import pyodbc

        host = connection_data.get("host")
        port = connection_data.get("port", 9999)
        database = connection_data.get("database")
        username = connection_data.get("username")
        password = connection_data.get("password")
        ssl = connection_data.get("ssl", False)

        conn_str = (
            f"DRIVER={{DenodoODBC Unicode}};"
            f"SERVER={host};"
            f"PORT={port};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
        )
        if ssl:
            conn_str += "SSL=true;"

        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()
            # Query Denodo catalog
            cursor.execute("""
                SELECT database_name, view_name, view_type
                FROM CATALOG_VDP_METADATA_VIEWS()
                ORDER BY database_name, view_name
            """)
            tables = [
                {"schema": row[0], "name": row[1], "type": row[2]}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return tables
        finally:
            conn.close()

    @classmethod
    def get_columns(cls, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        import pyodbc

        host = connection_data.get("host")
        port = connection_data.get("port", 9999)
        database = connection_data.get("database")
        username = connection_data.get("username")
        password = connection_data.get("password")
        ssl = connection_data.get("ssl", False)

        conn_str = (
            f"DRIVER={{DenodoODBC Unicode}};"
            f"SERVER={host};"
            f"PORT={port};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
        )
        if ssl:
            conn_str += "SSL=true;"

        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()
            cursor.execute(f"DESC VIEW {table_name}")
            columns = [
                {"name": row[0], "type": row[1], "nullable": True, "default": None}
                for row in cursor.fetchall()
            ]
            cursor.close()
            return columns
        finally:
            conn.close()


# Registry of all available handlers
HANDLERS: Dict[str, type[BaseDBHandler]] = {
    # Databases
    "postgres": PostgresHandler,
    "mysql": MySQLHandler,
    "sqlserver": SQLServerHandler,
    "oracle": OracleHandler,
    "saphana": SAPHANAHandler,
    "teradata": TeradataHandler,
    "singlestore": SingleStoreHandler,
    "mariadb": MariaDBHandler,
    "cockroachdb": CockroachDBHandler,
    "clickhouse": ClickHouseHandler,
    # Cloud Data Platforms / Data Warehouses
    "snowflake": SnowflakeHandler,
    "bigquery": BigQueryHandler,
    "redshift": RedshiftHandler,
    "databricks": DatabricksHandler,
    "azuresynapse": AzureSynapseHandler,
    # Query Engines
    "athena": AthenaHandler,
    "trino": TrinoHandler,
    "presto": PrestoHandler,
    "dremio": DremioHandler,
    "starburst": StarburstHandler,
    # File-based Data Sources
    "csv": CSVFileHandler,
    "google_sheets": GoogleSheetsHandler,
    # Other Data Sources
    "looker": LookerHandler,
    "denodo": DenodoHandler,
}


class DBHandlerService:
    """Service for managing database handlers."""

    @staticmethod
    def get_available_handlers() -> List[HandlerInfo]:
        """Get list of all available database handlers with their metadata."""
        handlers = []
        for handler_class in HANDLERS.values():
            handlers.append(handler_class.get_info())
        return handlers

    @staticmethod
    def get_handler(db_type: str) -> Optional[type[BaseDBHandler]]:
        """Get a handler class by database type."""
        return HANDLERS.get(db_type)

    @staticmethod
    def get_handler_info(db_type: str) -> Optional[HandlerInfo]:
        """Get handler information by database type."""
        handler = HANDLERS.get(db_type)
        if handler:
            return handler.get_info()
        return None

    @staticmethod
    def test_connection(db_type: str, connection_data: Dict[str, Any]) -> ConnectionTestResult:
        """Test a database connection."""
        handler = HANDLERS.get(db_type)
        if not handler:
            return ConnectionTestResult(
                success=False,
                message=f"Unknown database type: {db_type}",
                error="Handler not found"
            )

        if not handler.is_available():
            return ConnectionTestResult(
                success=False,
                message=f"Driver for {db_type} is not installed",
                error="Driver not available"
            )

        return handler.test_connection(connection_data)

    @staticmethod
    def get_tables(db_type: str, connection_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get tables from a database."""
        handler = HANDLERS.get(db_type)
        if not handler:
            raise ValueError(f"Unknown database type: {db_type}")
        return handler.get_tables(connection_data)

    @staticmethod
    def get_columns(db_type: str, connection_data: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
        """Get columns for a table."""
        handler = HANDLERS.get(db_type)
        if not handler:
            raise ValueError(f"Unknown database type: {db_type}")
        return handler.get_columns(connection_data, table_name)

    @staticmethod
    def get_sample_data(db_type: str, connection_data: Dict[str, Any], table_name: str, limit: int = 1) -> Dict[str, Any]:
        """
        Get sample data from a table.
        Returns a dictionary mapping column names to sample values.
        """
        handler = HANDLERS.get(db_type)
        if not handler:
            raise ValueError(f"Unknown database type: {db_type}")

        # Check if handler has a custom get_sample_data method
        if hasattr(handler, 'get_sample_data'):
            return handler.get_sample_data(connection_data, table_name, limit)

        # Default implementation using SQL query
        # Build a simple SELECT query based on db type
        sample_data = {}

        try:
            if db_type == "postgres":
                import psycopg2
                conn = psycopg2.connect(
                    host=connection_data.get("host"),
                    port=connection_data.get("port", 5432),
                    dbname=connection_data.get("database"),
                    user=connection_data.get("username") or connection_data.get("user"),
                    password=connection_data.get("password"),
                )
                try:
                    cursor = conn.cursor()
                    cursor.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
                    if cursor.description:
                        columns = [desc[0] for desc in cursor.description]
                        row = cursor.fetchone()
                        if row:
                            for i, col_name in enumerate(columns):
                                sample_data[col_name] = row[i]
                finally:
                    conn.close()

            elif db_type == "mysql":
                import mysql.connector
                conn = mysql.connector.connect(
                    host=connection_data.get("host"),
                    port=connection_data.get("port", 3306),
                    database=connection_data.get("database"),
                    user=connection_data.get("username") or connection_data.get("user"),
                    password=connection_data.get("password"),
                )
                try:
                    cursor = conn.cursor()
                    # Parse schema.table if provided
                    if "." in table_name:
                        _, tbl = table_name.split(".", 1)
                    else:
                        tbl = table_name
                    cursor.execute(f"SELECT * FROM `{tbl}` LIMIT {limit}")
                    if cursor.description:
                        columns = [desc[0] for desc in cursor.description]
                        row = cursor.fetchone()
                        if row:
                            for i, col_name in enumerate(columns):
                                sample_data[col_name] = row[i]
                finally:
                    conn.close()

            elif db_type == "sqlserver":
                import pymssql
                conn = pymssql.connect(
                    server=connection_data.get("host"),
                    port=connection_data.get("port", 1433),
                    database=connection_data.get("database"),
                    user=connection_data.get("username") or connection_data.get("user"),
                    password=connection_data.get("password"),
                )
                try:
                    cursor = conn.cursor()
                    cursor.execute(f"SELECT TOP {limit} * FROM {table_name}")
                    if cursor.description:
                        columns = [desc[0] for desc in cursor.description]
                        row = cursor.fetchone()
                        if row:
                            for i, col_name in enumerate(columns):
                                sample_data[col_name] = row[i]
                finally:
                    conn.close()

            elif db_type == "snowflake":
                import snowflake.connector
                conn = snowflake.connector.connect(
                    account=connection_data.get("account"),
                    user=connection_data.get("user") or connection_data.get("username"),
                    password=connection_data.get("password"),
                    warehouse=connection_data.get("warehouse"),
                    database=connection_data.get("database"),
                    schema=connection_data.get("schema", "PUBLIC"),
                )
                try:
                    cursor = conn.cursor()
                    cursor.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
                    if cursor.description:
                        columns = [desc[0] for desc in cursor.description]
                        row = cursor.fetchone()
                        if row:
                            for i, col_name in enumerate(columns):
                                sample_data[col_name] = row[i]
                finally:
                    conn.close()

            # Add more handlers as needed, or return empty dict for unsupported types
        except Exception as e:
            logger.warning(f"Failed to get sample data for {table_name}: {e}")

        return sample_data

    @staticmethod
    def get_sample_rows(db_type: str, connection_data: Dict[str, Any], table_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get multiple sample rows from a table.
        Returns a list of dictionaries, each representing a row.
        """
        handler = HANDLERS.get(db_type)
        if not handler:
            raise ValueError(f"Unknown database type: {db_type}")

        rows = []

        try:
            if db_type == "postgres":
                import psycopg2
                conn = psycopg2.connect(
                    host=connection_data.get("host"),
                    port=connection_data.get("port", 5432),
                    dbname=connection_data.get("database"),
                    user=connection_data.get("username") or connection_data.get("user"),
                    password=connection_data.get("password"),
                )
                try:
                    cursor = conn.cursor()
                    cursor.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
                    if cursor.description:
                        columns = [desc[0] for desc in cursor.description]
                        for row in cursor.fetchall():
                            row_dict = {}
                            for i, col_name in enumerate(columns):
                                val = row[i]
                                # Convert to JSON-serializable format
                                if hasattr(val, 'isoformat'):
                                    val = val.isoformat()
                                elif isinstance(val, (bytes, memoryview)):
                                    val = str(val)
                                row_dict[col_name] = val
                            rows.append(row_dict)
                finally:
                    conn.close()

            elif db_type == "mysql":
                import mysql.connector
                conn = mysql.connector.connect(
                    host=connection_data.get("host"),
                    port=connection_data.get("port", 3306),
                    database=connection_data.get("database"),
                    user=connection_data.get("username") or connection_data.get("user"),
                    password=connection_data.get("password"),
                )
                try:
                    cursor = conn.cursor()
                    if "." in table_name:
                        _, tbl = table_name.split(".", 1)
                    else:
                        tbl = table_name
                    cursor.execute(f"SELECT * FROM `{tbl}` LIMIT {limit}")
                    if cursor.description:
                        columns = [desc[0] for desc in cursor.description]
                        for row in cursor.fetchall():
                            row_dict = {}
                            for i, col_name in enumerate(columns):
                                val = row[i]
                                if hasattr(val, 'isoformat'):
                                    val = val.isoformat()
                                elif isinstance(val, (bytes, memoryview)):
                                    val = str(val)
                                row_dict[col_name] = val
                            rows.append(row_dict)
                finally:
                    conn.close()

            elif db_type == "sqlserver":
                import pymssql
                conn = pymssql.connect(
                    server=connection_data.get("host"),
                    port=connection_data.get("port", 1433),
                    database=connection_data.get("database"),
                    user=connection_data.get("username") or connection_data.get("user"),
                    password=connection_data.get("password"),
                )
                try:
                    cursor = conn.cursor()
                    cursor.execute(f"SELECT TOP {limit} * FROM {table_name}")
                    if cursor.description:
                        columns = [desc[0] for desc in cursor.description]
                        for row in cursor.fetchall():
                            row_dict = {}
                            for i, col_name in enumerate(columns):
                                val = row[i]
                                if hasattr(val, 'isoformat'):
                                    val = val.isoformat()
                                elif isinstance(val, (bytes, memoryview)):
                                    val = str(val)
                                row_dict[col_name] = val
                            rows.append(row_dict)
                finally:
                    conn.close()

            elif db_type == "snowflake":
                import snowflake.connector
                conn = snowflake.connector.connect(
                    account=connection_data.get("account"),
                    user=connection_data.get("user") or connection_data.get("username"),
                    password=connection_data.get("password"),
                    warehouse=connection_data.get("warehouse"),
                    database=connection_data.get("database"),
                    schema=connection_data.get("schema", "PUBLIC"),
                )
                try:
                    cursor = conn.cursor()
                    cursor.execute(f"SELECT * FROM {table_name} LIMIT {limit}")
                    if cursor.description:
                        columns = [desc[0] for desc in cursor.description]
                        for row in cursor.fetchall():
                            row_dict = {}
                            for i, col_name in enumerate(columns):
                                val = row[i]
                                if hasattr(val, 'isoformat'):
                                    val = val.isoformat()
                                elif isinstance(val, (bytes, memoryview)):
                                    val = str(val)
                                row_dict[col_name] = val
                            rows.append(row_dict)
                finally:
                    conn.close()

        except Exception as e:
            logger.warning(f"Failed to get sample rows for {table_name}: {e}")

        return rows

    @staticmethod
    def get_column_statistics(db_type: str, connection_data: Dict[str, Any], table_name: str, column_name: str) -> Dict[str, Any]:
        """
        Get statistics for a specific column.
        Returns null_count, min_value, max_value, avg_value, sum_value, distinct_count.
        """
        handler = HANDLERS.get(db_type)
        if not handler:
            raise ValueError(f"Unknown database type: {db_type}")

        stats = {
            "null_count": None,
            "min_value": None,
            "max_value": None,
            "avg_value": None,
            "sum_value": None,
            "distinct_count": None,
        }

        try:
            if db_type == "postgres":
                import psycopg2
                conn = psycopg2.connect(
                    host=connection_data.get("host"),
                    port=connection_data.get("port", 5432),
                    dbname=connection_data.get("database"),
                    user=connection_data.get("username") or connection_data.get("user"),
                    password=connection_data.get("password"),
                )
                try:
                    cursor = conn.cursor()
                    query = f"""
                        SELECT
                            COUNT(*) - COUNT("{column_name}") as null_count,
                            MIN("{column_name}")::text as min_value,
                            MAX("{column_name}")::text as max_value,
                            COUNT(DISTINCT "{column_name}") as distinct_count
                        FROM {table_name}
                    """
                    cursor.execute(query)
                    row = cursor.fetchone()
                    if row:
                        stats["null_count"] = row[0]
                        stats["min_value"] = row[1]
                        stats["max_value"] = row[2]
                        stats["distinct_count"] = row[3]

                    # Try numeric aggregates separately
                    try:
                        cursor.execute(f'SELECT AVG("{column_name}"::numeric), SUM("{column_name}"::numeric) FROM {table_name}')
                        num_row = cursor.fetchone()
                        if num_row and num_row[0] is not None:
                            stats["avg_value"] = float(num_row[0])
                            stats["sum_value"] = float(num_row[1])
                    except:
                        pass
                finally:
                    conn.close()

            elif db_type == "mysql":
                import mysql.connector
                conn = mysql.connector.connect(
                    host=connection_data.get("host"),
                    port=connection_data.get("port", 3306),
                    database=connection_data.get("database"),
                    user=connection_data.get("username") or connection_data.get("user"),
                    password=connection_data.get("password"),
                )
                try:
                    cursor = conn.cursor()
                    if "." in table_name:
                        _, tbl = table_name.split(".", 1)
                    else:
                        tbl = table_name
                    query = f"""
                        SELECT
                            SUM(CASE WHEN `{column_name}` IS NULL THEN 1 ELSE 0 END) as null_count,
                            MIN(`{column_name}`) as min_value,
                            MAX(`{column_name}`) as max_value,
                            COUNT(DISTINCT `{column_name}`) as distinct_count,
                            AVG(`{column_name}`) as avg_value,
                            SUM(`{column_name}`) as sum_value
                        FROM `{tbl}`
                    """
                    cursor.execute(query)
                    row = cursor.fetchone()
                    if row:
                        stats["null_count"] = int(row[0]) if row[0] is not None else 0
                        stats["min_value"] = str(row[1]) if row[1] is not None else None
                        stats["max_value"] = str(row[2]) if row[2] is not None else None
                        stats["distinct_count"] = row[3]
                        stats["avg_value"] = float(row[4]) if row[4] is not None else None
                        stats["sum_value"] = float(row[5]) if row[5] is not None else None
                finally:
                    conn.close()

        except Exception as e:
            logger.warning(f"Failed to get column statistics for {table_name}.{column_name}: {e}")

        return stats
