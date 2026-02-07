"""Oracle database handler implementation."""

import logging
from typing import Optional

import pandas as pd
import oracledb

from src.data_connectors.libs.constants import DataType, HandlerType
from src.data_connectors.libs.database_handler import MetaDatabaseHandler
from src.data_connectors.libs.response import HandlerResponse, HandlerStatus

logger = logging.getLogger(__name__)


class OracleHandler(MetaDatabaseHandler):
    """Handler for Oracle databases."""

    handler_name = "oracle"
    handler_type = HandlerType.DATA
    handler_title = "Oracle"
    handler_description = "Connect to Oracle databases"
    handler_version = "0.1.0"
    dialect = "oracle"

    type_mapping = {
        ("number",): DataType.DECIMAL,  # Can be int or decimal based on scale
        ("binary_float",): DataType.FLOAT,
        ("binary_double",): DataType.DOUBLE,
        ("float",): DataType.DOUBLE,
        ("char", "nchar"): DataType.CHAR,
        ("varchar2", "nvarchar2"): DataType.VARCHAR,
        ("clob", "nclob", "long"): DataType.TEXT,
        ("blob", "raw", "long raw"): DataType.BLOB,
        ("date",): DataType.DATETIME,
        ("timestamp", "timestamp with time zone", "timestamp with local time zone"): DataType.TIMESTAMP,
        ("interval year to month", "interval day to second"): DataType.VARCHAR,
        ("rowid", "urowid"): DataType.VARCHAR,
        ("xmltype"): DataType.TEXT,
        ("json",): DataType.JSON,
        ("boolean",): DataType.BOOLEAN,
    }

    def __init__(self, name: str, connection_args: dict):
        super().__init__(name, connection_args)
        self._user = connection_args.get("user")

    def connect(self) -> None:
        """Establish connection to Oracle database."""
        if self.is_connected:
            return

        try:
            # Build DSN
            if self.connection_args.get("dsn"):
                dsn = self.connection_args["dsn"]
            else:
                host = self.connection_args["host"]
                port = self.connection_args.get("port", 1521)

                if self.connection_args.get("service_name"):
                    dsn = oracledb.makedsn(
                        host, port,
                        service_name=self.connection_args["service_name"]
                    )
                elif self.connection_args.get("sid"):
                    dsn = oracledb.makedsn(
                        host, port,
                        sid=self.connection_args["sid"]
                    )
                else:
                    raise ValueError("Either 'service_name', 'sid', or 'dsn' must be provided")

            self._connection = oracledb.connect(
                user=self.connection_args["user"],
                password=self.connection_args["password"],
                dsn=dsn,
            )
            self.is_connected = True
            logger.info(f"Connected to Oracle: {self.name}")

        except Exception as e:
            self.is_connected = False
            logger.error(f"Failed to connect to Oracle: {e}")
            raise ConnectionError(f"Failed to connect to Oracle: {e}")

    def disconnect(self) -> None:
        """Close the Oracle connection."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            finally:
                self._connection = None
                self.is_connected = False
                logger.info(f"Disconnected from Oracle: {self.name}")

    def check_connection(self) -> HandlerStatus:
        """Check if the Oracle connection is working."""
        try:
            if not self.is_connected:
                self.connect()

            cursor = self._connection.cursor()
            cursor.execute("SELECT * FROM V$VERSION WHERE BANNER LIKE 'Oracle%'")
            row = cursor.fetchone()
            version = row[0] if row else "Unknown"
            cursor.close()

            return HandlerStatus.success({
                "version": version,
                "user": self._user,
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
        """List all tables accessible to the user."""
        query = """
            SELECT
                owner AS table_schema,
                table_name,
                'BASE TABLE' AS table_type
            FROM all_tables
            WHERE owner = USER
            UNION ALL
            SELECT
                owner AS table_schema,
                view_name AS table_name,
                'VIEW' AS table_type
            FROM all_views
            WHERE owner = USER
            ORDER BY table_name
        """
        return self.native_query(query)

    def get_columns(self, table_name: str) -> HandlerResponse:
        """Get column information for a table."""
        query = f"""
            SELECT
                column_name,
                data_type,
                column_id AS ordinal_position,
                data_default AS column_default,
                nullable AS is_nullable,
                data_length AS max_length,
                data_precision AS numeric_precision,
                data_scale AS numeric_scale
            FROM all_tab_columns
            WHERE owner = USER
                AND table_name = UPPER('{table_name}')
            ORDER BY column_id
        """
        result = self.native_query(query)
        if result.success and result.data is not None:
            for idx, row in result.data.iterrows():
                data_type = row['data_type'].lower() if row['data_type'] else 'varchar2'
                # Special handling for NUMBER type
                if data_type == 'number':
                    scale = row.get('numeric_scale')
                    if scale == 0 or scale is None:
                        result.data.at[idx, 'canonical_type'] = DataType.INTEGER.value
                    else:
                        result.data.at[idx, 'canonical_type'] = DataType.DECIMAL.value
                else:
                    result.data.at[idx, 'canonical_type'] = self.map_type(data_type).value
        return result

    def get_primary_keys(self, table_name: str) -> HandlerResponse:
        """Get primary key columns for a table."""
        query = f"""
            SELECT
                ac.constraint_name,
                acc.column_name,
                acc.position AS ordinal_position
            FROM all_constraints ac
            JOIN all_cons_columns acc
                ON ac.constraint_name = acc.constraint_name
                AND ac.owner = acc.owner
            WHERE ac.constraint_type = 'P'
                AND ac.owner = USER
                AND ac.table_name = UPPER('{table_name}')
            ORDER BY acc.position
        """
        return self.native_query(query)

    def get_foreign_keys(self, table_name: str) -> HandlerResponse:
        """Get foreign key relationships for a table."""
        query = f"""
            SELECT
                a.constraint_name,
                a.column_name AS child_column,
                c_pk.table_name AS parent_table,
                b.column_name AS parent_column
            FROM all_cons_columns a
            JOIN all_constraints c
                ON a.constraint_name = c.constraint_name
                AND a.owner = c.owner
            JOIN all_constraints c_pk
                ON c.r_constraint_name = c_pk.constraint_name
            JOIN all_cons_columns b
                ON c_pk.constraint_name = b.constraint_name
                AND a.position = b.position
            WHERE c.constraint_type = 'R'
                AND a.owner = USER
                AND a.table_name = UPPER('{table_name}')
        """
        return self.native_query(query)

    def get_indexes(self, table_name: str) -> HandlerResponse:
        """Get indexes for a table."""
        query = f"""
            SELECT
                index_name,
                column_name,
                column_position,
                descend
            FROM all_ind_columns
            WHERE table_owner = USER
                AND table_name = UPPER('{table_name}')
            ORDER BY index_name, column_position
        """
        return self.native_query(query)

    def _quote_identifier(self, identifier: str) -> str:
        """Quote an Oracle identifier."""
        return f'"{identifier.upper()}"'
