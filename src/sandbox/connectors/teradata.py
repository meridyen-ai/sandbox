"""
Teradata Connector

Uses the teradatasql driver. A "schema" is a Teradata database.
"""

from __future__ import annotations

from typing import Any

from sandbox.connectors.dbapi import DBAPIConnector
from sandbox.connectors.tls import VERIFYING_SSL_MODES

# DBC.ColumnsV spells a column's type as a two-letter code.
_TYPE_NAMES = {
    "A1": "ARRAY", "AN": "ARRAY", "AT": "TIME", "BF": "BYTE", "BO": "BLOB",
    "BV": "VARBYTE", "CF": "CHAR", "CO": "CLOB", "CV": "VARCHAR", "D": "DECIMAL",
    "DA": "DATE", "DH": "INTERVAL DAY TO HOUR", "DM": "INTERVAL DAY TO MINUTE",
    "DS": "INTERVAL DAY TO SECOND", "DY": "INTERVAL DAY", "F": "FLOAT",
    "HM": "INTERVAL HOUR TO MINUTE", "HR": "INTERVAL HOUR",
    "HS": "INTERVAL HOUR TO SECOND", "I": "INTEGER", "I1": "BYTEINT",
    "I2": "SMALLINT", "I8": "BIGINT", "JN": "JSON", "MI": "INTERVAL MINUTE",
    "MO": "INTERVAL MONTH", "MS": "INTERVAL MINUTE TO SECOND", "N": "NUMBER",
    "PD": "PERIOD(DATE)", "PM": "PERIOD(TIMESTAMP WITH TIME ZONE)",
    "PS": "PERIOD(TIMESTAMP)", "PT": "PERIOD(TIME)",
    "PZ": "PERIOD(TIME WITH TIME ZONE)", "SC": "INTERVAL SECOND",
    "SZ": "TIMESTAMP WITH TIME ZONE", "TS": "TIMESTAMP",
    "TZ": "TIME WITH TIME ZONE", "UT": "UDT", "XM": "XML",
    "YM": "INTERVAL YEAR TO MONTH", "YR": "INTERVAL YEAR",
}


class TeradataConnector(DBAPIConnector):
    """Teradata Vantage."""

    label = "Teradata"
    driver_modules = ("teradatasql",)

    def _open(self) -> Any:
        import teradatasql

        cfg = self.config
        # The driver takes every setting as a string.
        params: dict[str, str] = {
            "host": cfg.host,
            "user": cfg.username,
            "password": cfg.password.get_secret_value(),
            "connect_timeout": str(cfg.connection_timeout * 1000),
        }
        if cfg.database:
            params["database"] = cfg.database
        port = self._param("dbs_port")
        if port:
            params["dbs_port"] = str(port)
        # A connection that states no mode gets the driver's own (PREFER).
        if cfg.ssl_mode or cfg.ssl_enabled:
            mode = self._ssl_mode()
            params["sslmode"] = mode.upper()
            if mode in VERIFYING_SSL_MODES:
                params["sslca"] = self._trust_store(mode)
        return teradatasql.connect(**params)

    def _default_schema(self) -> str | None:
        return self.config.database or self.config.username or None

    def _entries_query(self, schema: str | None) -> tuple[str, tuple[Any, ...]]:
        return (
            "SELECT TRIM(TableName), CASE WHEN TableKind = 'V' THEN 'VIEW' ELSE 'TABLE' END "
            "FROM DBC.TablesV WHERE DataBaseName = ? AND TableKind IN ('T', 'O', 'V')",
            (schema,),
        )

    def _columns_query(
        self, schema: str | None, table: str | None
    ) -> tuple[str, tuple[Any, ...]]:
        sql = (
            "SELECT TRIM(TableName), TRIM(ColumnName), TRIM(ColumnType), Nullable, "
            "DefaultValue, ColumnLength, DecimalTotalDigits, DecimalFractionalDigits "
            "FROM DBC.ColumnsV WHERE DatabaseName = ?"
        )
        args: tuple[Any, ...] = (schema,)
        if table is not None:
            sql += " AND TableName = ?"
            args += (table,)
        return sql + " ORDER BY TableName, ColumnId", args

    def _fetch(self, conn: Any, sql: str, args: Any) -> list[Any]:
        rows = super()._fetch(conn, sql, args)
        if "DBC.ColumnsV" not in sql:
            return rows
        return [
            (row[0], row[1], _TYPE_NAMES.get(row[2] or "", row[2] or ""), *row[3:])
            for row in rows
        ]
