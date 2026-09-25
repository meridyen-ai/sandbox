"""
Schema helpers shared by the schema endpoints.

* ``build_sample_query`` — the one place sample-row SQL is spelled, per dialect.
* ``merge_virtual_entries`` / ``virtual_columns`` — fold a connection's virtual
  objects into catalog and column listings, so they reach every consumer
  (table pickers, schema cache, agent context) exactly like tables do.
"""

from __future__ import annotations

import os
from typing import Any

from sandbox.execution.virtual_objects.models import KIND_PROCEDURE, VirtualObject
from sandbox.execution.virtual_objects.registry import VirtualObjectSet


def quote_ident(db_type: str, name: str) -> str:
    if db_type == "mssql":
        return "[" + str(name).replace("]", "]]") + "]"
    if db_type == "mysql":
        return "`" + str(name).replace("`", "``") + "`"
    return '"' + str(name).replace('"', '""') + '"'


def build_sample_query(
    db_type: str,
    schema: str | None,
    table: str,
    columns: list[str] | None,
    limit: int,
) -> str:
    limit = max(1, int(limit))
    cols = ", ".join(quote_ident(db_type, c) for c in columns) if columns else "*"
    ref = quote_ident(db_type, table)
    if schema:
        ref = f"{quote_ident(db_type, schema)}.{ref}"
    if db_type == "mssql":
        return f"SELECT TOP {limit} {cols} FROM {ref}"
    return f"SELECT {cols} FROM {ref} LIMIT {limit}"


def merge_virtual_entries(
    entries: list[dict[str, Any]], objects: VirtualObjectSet
) -> tuple[list[dict[str, Any]], list[VirtualObject]]:
    """Catalog entries plus virtual objects (type QUERY / PROCEDURE).

    A real table or view with the same name as a virtual object is dropped:
    SQL referencing the name is expanded to the virtual object, so that is
    what the name means. Returns the objects that collided so the caller can
    flag them.
    """
    if not objects:
        return entries, []
    real = [e for e in entries if e["name"].lower() not in objects.by_name]
    names = {e["name"].lower() for e in entries}
    conflicts = [o for o in objects.by_name.values() if o.key in names]
    virtual = [{"name": o.name, "type": o.kind} for o in objects.by_name.values()]
    merged = sorted(real + virtual, key=lambda e: e["name"].lower())
    return merged, conflicts


def virtual_column_info(obj: VirtualObject) -> list[dict[str, Any]]:
    """Columns in the shape connectors' get_columns/get_all_columns return."""
    return [
        {
            "name": c.name,
            "type": c.sql_type,
            "nullable": c.nullable,
            "default": None,
            "max_length": None,
            "precision": None,
            "scale": None,
            "is_primary_key": False,
            "is_unique": False,
            "is_foreign_key": False,
            "foreign_table": None,
        }
        for c in obj.columns
    ]


def virtual_columns(objects: VirtualObjectSet) -> dict[str, list[dict[str, Any]]]:
    return {o.name: virtual_column_info(o) for o in objects.by_name.values()}


def samples_enabled_for(obj: VirtualObject | None) -> bool:
    """Procedures run in full to produce sample rows; allow switching that off."""
    if obj is None or obj.kind != KIND_PROCEDURE:
        return True
    return os.environ.get("SANDBOX_VO_SAMPLE_PROCEDURES", "true").lower() not in ("0", "false", "no")
