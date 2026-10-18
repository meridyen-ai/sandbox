"""
Denodo Connector

A Denodo Virtual DataPort server answers the PostgreSQL wire protocol on its
ODBC port (9996 by default), which is how it is reached here. Its catalog is
read through Denodo's own metadata procedures; a "schema" is a virtual
database.
"""

from __future__ import annotations

from typing import Any

from sandbox.connectors.dbapi import _close_quietly
from sandbox.connectors.redshift import LibpqConnector


class DenodoConnector(LibpqConnector):
    """Denodo Virtual DataPort."""

    label = "Denodo"
    default_port = 9996

    def _default_schema(self) -> str | None:
        return self.config.database or None

    def _entries_query(self, schema: str | None) -> tuple[str, tuple[Any, ...]]:
        return (
            "SELECT view_name, view_type FROM CATALOG_VDP_METADATA_VIEWS() "
            "WHERE input_database_name = %s",
            (schema,),
        )

    def _columns_query(
        self, schema: str | None, table: str | None
    ) -> tuple[str, tuple[Any, ...]]:
        sql = "SELECT * FROM GET_VIEW_COLUMNS() WHERE input_database_name = %s"
        args: tuple[Any, ...] = (schema,)
        if table is not None:
            sql += " AND input_view_name = %s"
            args += (table,)
        return sql, args

    def _fetch(self, conn: Any, sql: str, args: Any) -> list[Any]:
        if "GET_VIEW_COLUMNS()" not in sql:
            return super()._fetch(conn, sql, args)
        # The procedure's output fields differ between Denodo versions, so
        # they are read by name and the ones a version lacks are left empty.
        cursor = conn.cursor()
        try:
            cursor.execute(sql, args)
            names = [str(d[0]).lower() for d in cursor.description]
            records = [dict(zip(names, row)) for row in cursor.fetchall()]
        finally:
            _close_quietly(cursor)
        records.sort(key=lambda r: (str(r.get("view_name")), r.get("ordinal_position") or 0))
        return [
            (
                r.get("view_name"),
                r.get("column_name"),
                r.get("column_sql_type") or r.get("column_type_name") or "",
                r.get("column_is_nullable", True),
                None,
                r.get("column_type_length"),
                r.get("column_type_precision"),
                r.get("column_type_decimals"),
            )
            for r in records
        ]
