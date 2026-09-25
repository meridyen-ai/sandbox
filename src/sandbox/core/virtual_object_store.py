"""
Postgres-backed store for virtual objects (custom queries, stored procedures).

One row per object, owned by a connection (``ON DELETE CASCADE``). Kept out of
the ``connections`` row on purpose: ``update_connection`` rewrites every column,
so a JSONB blob there would lose concurrent edits, and each object needs its
own status and a unique name.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from sandbox.core.connection_store import _get_engine
from sandbox.core.logging import get_logger
from sandbox.execution.virtual_objects.models import (
    ParamSpec,
    VirtualColumn,
    VirtualObject,
)

logger = get_logger(__name__)


def ensure_virtual_objects_table() -> None:
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS virtual_objects (
                id                TEXT PRIMARY KEY,
                connection_id     TEXT NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
                kind              TEXT NOT NULL CHECK (kind IN ('QUERY', 'PROCEDURE')),
                name              TEXT NOT NULL,
                description       TEXT,
                sql_text          TEXT,
                normalized_sql    TEXT,
                routine_type      TEXT,
                routine_schema    TEXT,
                routine_name      TEXT,
                routine_signature TEXT,
                params            JSONB NOT NULL DEFAULT '[]',
                result_set_index  INTEGER NOT NULL DEFAULT 0,
                materialization   TEXT NOT NULL DEFAULT 'insert_exec',
                columns           JSONB NOT NULL DEFAULT '[]',
                cache_ttl_seconds INTEGER NOT NULL DEFAULT 0,
                definition_hash   TEXT NOT NULL DEFAULT '',
                status            TEXT NOT NULL DEFAULT 'ok',
                last_error        TEXT,
                last_validated_at TIMESTAMPTZ,
                created_by        TEXT,
                created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_virtual_objects_conn_name "
            "ON virtual_objects (connection_id, lower(name))"
        ))
    logger.info("virtual_objects_table_ensured")


def _row_to_object(row: Any) -> VirtualObject:
    m = row._mapping
    return VirtualObject(
        id=m["id"],
        connection_id=m["connection_id"],
        kind=m["kind"],
        name=m["name"],
        description=m["description"],
        sql_text=m["sql_text"],
        normalized_sql=m["normalized_sql"],
        routine_type=m["routine_type"],
        routine_schema=m["routine_schema"],
        routine_name=m["routine_name"],
        routine_signature=m["routine_signature"],
        params=[ParamSpec.from_dict(p) for p in (m["params"] or [])],
        result_set_index=m["result_set_index"] or 0,
        materialization=m["materialization"] or "insert_exec",
        columns=[VirtualColumn.from_dict(c) for c in (m["columns"] or [])],
        cache_ttl_seconds=m["cache_ttl_seconds"] or 0,
        definition_hash=m["definition_hash"] or "",
        status=m["status"] or "ok",
        last_error=m["last_error"],
        last_validated_at=m["last_validated_at"],
        created_by=m["created_by"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


def _params(obj: VirtualObject) -> dict[str, Any]:
    d = obj.to_dict()
    return {
        "id": obj.id,
        "connection_id": obj.connection_id,
        "kind": obj.kind,
        "name": obj.name,
        "description": obj.description,
        "sql_text": obj.sql_text,
        "normalized_sql": obj.normalized_sql,
        "routine_type": obj.routine_type,
        "routine_schema": obj.routine_schema,
        "routine_name": obj.routine_name,
        "routine_signature": obj.routine_signature,
        "params": json.dumps(d["params"]),
        "result_set_index": obj.result_set_index,
        "materialization": obj.materialization,
        "columns": json.dumps(d["columns"]),
        "cache_ttl_seconds": obj.cache_ttl_seconds,
        "definition_hash": obj.definition_hash,
        "status": obj.status,
        "last_error": obj.last_error,
        "last_validated_at": obj.last_validated_at,
        "created_by": obj.created_by,
    }


def list_for_connection(connection_id: str) -> list[VirtualObject]:
    with _get_engine().connect() as conn:
        rows = conn.execute(
            text("SELECT * FROM virtual_objects WHERE connection_id = :cid ORDER BY lower(name)"),
            {"cid": connection_id},
        ).fetchall()
    return [_row_to_object(r) for r in rows]


def get(object_id: str) -> VirtualObject | None:
    with _get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT * FROM virtual_objects WHERE id = :id"), {"id": object_id}
        ).fetchone()
    return _row_to_object(row) if row else None


def create(obj: VirtualObject) -> VirtualObject:
    obj.id = obj.id or str(uuid.uuid4())
    with _get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO virtual_objects
                (id, connection_id, kind, name, description, sql_text, normalized_sql,
                 routine_type, routine_schema, routine_name, routine_signature,
                 params, result_set_index, materialization, columns, cache_ttl_seconds,
                 definition_hash, status, last_error, last_validated_at, created_by)
            VALUES
                (:id, :connection_id, :kind, :name, :description, :sql_text, :normalized_sql,
                 :routine_type, :routine_schema, :routine_name, :routine_signature,
                 CAST(:params AS JSONB), :result_set_index, :materialization,
                 CAST(:columns AS JSONB), :cache_ttl_seconds,
                 :definition_hash, :status, :last_error, :last_validated_at, :created_by)
        """), _params(obj))
    return get(obj.id)  # type: ignore[return-value]


def update(obj: VirtualObject) -> VirtualObject | None:
    p = _params(obj)
    p["updated_at"] = datetime.now(timezone.utc)
    with _get_engine().begin() as conn:
        result = conn.execute(text("""
            UPDATE virtual_objects SET
                description = :description,
                sql_text = :sql_text,
                normalized_sql = :normalized_sql,
                routine_type = :routine_type,
                routine_schema = :routine_schema,
                routine_name = :routine_name,
                routine_signature = :routine_signature,
                params = CAST(:params AS JSONB),
                result_set_index = :result_set_index,
                materialization = :materialization,
                columns = CAST(:columns AS JSONB),
                cache_ttl_seconds = :cache_ttl_seconds,
                definition_hash = :definition_hash,
                status = :status,
                last_error = :last_error,
                last_validated_at = :last_validated_at,
                updated_at = :updated_at
            WHERE id = :id
        """), p)
    return get(obj.id) if result.rowcount else None


def set_status(object_id: str, status: str, last_error: str | None) -> None:
    with _get_engine().begin() as conn:
        conn.execute(
            text("""
                UPDATE virtual_objects
                SET status = :status, last_error = :err, last_validated_at = NOW()
                WHERE id = :id
            """),
            {"id": object_id, "status": status, "err": last_error},
        )


def delete(object_id: str) -> bool:
    with _get_engine().begin() as conn:
        result = conn.execute(
            text("DELETE FROM virtual_objects WHERE id = :id"), {"id": object_id}
        )
    return result.rowcount > 0
