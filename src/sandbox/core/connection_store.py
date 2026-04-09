"""
Postgres-backed connection store.

Replaces the old connections.json file with a proper database table
in the sandbox PostgreSQL database (sandbox_uploads).
"""

from __future__ import annotations

import os
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import Engine

from sandbox.core.logging import get_logger

logger = get_logger(__name__)

# Re-use the same upload DB credentials (sandbox-postgres / sandbox_uploads)
_DB_HOST = os.environ.get("SANDBOX_UPLOAD_DB_HOST", "sandbox-postgres")
_DB_PORT = int(os.environ.get("SANDBOX_UPLOAD_DB_PORT", "5432"))
_DB_NAME = os.environ.get("SANDBOX_UPLOAD_DB_NAME", "sandbox_uploads")
_DB_USER = os.environ.get("SANDBOX_UPLOAD_DB_USER", "sandbox")
_DB_PASSWORD = os.environ.get("SANDBOX_UPLOAD_DB_PASSWORD", "sandbox_password")

# Old JSON file path (for migration)
_LEGACY_JSON_PATH = Path("/app/data/connections.json")

_engine: Engine | None = None


def _get_engine() -> Engine:
    """Get or create the SQLAlchemy engine for the sandbox DB."""
    global _engine
    if _engine is None:
        from sqlalchemy import create_engine
        url = (
            f"postgresql+psycopg2://{_DB_USER}:{_DB_PASSWORD}"
            f"@{_DB_HOST}:{_DB_PORT}/{_DB_NAME}"
        )
        _engine = create_engine(url, pool_pre_ping=True, pool_size=5)
    return _engine


def ensure_connections_table() -> None:
    """Create the connections table if it doesn't exist."""
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS connections (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                db_type         TEXT NOT NULL,
                host            TEXT NOT NULL,
                port            INTEGER NOT NULL DEFAULT 0,
                database        TEXT NOT NULL DEFAULT '',
                username        TEXT NOT NULL DEFAULT '',
                password        TEXT NOT NULL DEFAULT '',
                schema_name     TEXT,
                ssl_enabled     BOOLEAN NOT NULL DEFAULT FALSE,
                ssl_ca_cert     TEXT,
                connection_timeout INTEGER NOT NULL DEFAULT 30,
                query_timeout   INTEGER NOT NULL DEFAULT 300,
                max_pool_size   INTEGER NOT NULL DEFAULT 10,
                extra_params    JSONB NOT NULL DEFAULT '{}',
                selected_tables JSONB,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))
    logger.info("connections_table_ensured")


def _row_to_dict(row: Any) -> dict:
    """Convert a SQLAlchemy row to a plain dict."""
    mapping = row._mapping
    return {
        "id": mapping["id"],
        "name": mapping["name"],
        "db_type": mapping["db_type"],
        "host": mapping["host"],
        "port": mapping["port"],
        "database": mapping["database"],
        "username": mapping["username"],
        "password": mapping["password"],
        "schema_name": mapping["schema_name"],
        "ssl_enabled": mapping["ssl_enabled"],
        "ssl_ca_cert": mapping["ssl_ca_cert"],
        "connection_timeout": mapping["connection_timeout"],
        "query_timeout": mapping["query_timeout"],
        "max_pool_size": mapping["max_pool_size"],
        "extra_params": mapping["extra_params"] or {},
        "selected_tables": mapping["selected_tables"],
        "created_at": mapping["created_at"].isoformat() if mapping["created_at"] else None,
        "updated_at": mapping["updated_at"].isoformat() if mapping["updated_at"] else None,
    }


# --------------- CRUD ---------------


def list_connections() -> list[dict]:
    """Return all connections as dicts."""
    engine = _get_engine()
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM connections ORDER BY created_at")).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_connection(connection_id: str) -> dict | None:
    """Return a single connection dict or None."""
    engine = _get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM connections WHERE id = :id"),
            {"id": connection_id},
        ).fetchone()
    return _row_to_dict(row) if row else None


def create_connection(data: dict) -> dict:
    """Insert a new connection and return it."""
    conn_id = data.get("id") or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO connections
                (id, name, db_type, host, port, database, username, password,
                 schema_name, ssl_enabled, ssl_ca_cert,
                 connection_timeout, query_timeout, max_pool_size,
                 extra_params, selected_tables, created_at, updated_at)
            VALUES
                (:id, :name, :db_type, :host, :port, :database, :username, :password,
                 :schema_name, :ssl_enabled, :ssl_ca_cert,
                 :connection_timeout, :query_timeout, :max_pool_size,
                 :extra_params, :selected_tables, :created_at, :updated_at)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                db_type = EXCLUDED.db_type,
                host = EXCLUDED.host,
                port = EXCLUDED.port,
                database = EXCLUDED.database,
                username = EXCLUDED.username,
                password = EXCLUDED.password,
                schema_name = EXCLUDED.schema_name,
                ssl_enabled = EXCLUDED.ssl_enabled,
                ssl_ca_cert = EXCLUDED.ssl_ca_cert,
                connection_timeout = EXCLUDED.connection_timeout,
                query_timeout = EXCLUDED.query_timeout,
                max_pool_size = EXCLUDED.max_pool_size,
                extra_params = EXCLUDED.extra_params,
                selected_tables = EXCLUDED.selected_tables,
                updated_at = EXCLUDED.updated_at
        """), {
            "id": conn_id,
            "name": data.get("name", ""),
            "db_type": data.get("db_type", "postgresql"),
            "host": data.get("host", "localhost"),
            "port": data.get("port", 0),
            "database": data.get("database", ""),
            "username": data.get("username", ""),
            "password": data.get("password", ""),
            "schema_name": data.get("schema_name"),
            "ssl_enabled": data.get("ssl_enabled", False),
            "ssl_ca_cert": data.get("ssl_ca_cert"),
            "connection_timeout": data.get("connection_timeout", 30),
            "query_timeout": data.get("query_timeout", 300),
            "max_pool_size": data.get("max_pool_size", 10),
            "extra_params": json.dumps(data.get("extra_params", {})),
            "selected_tables": json.dumps(data.get("selected_tables")) if data.get("selected_tables") else None,
            "created_at": now,
            "updated_at": now,
        })
    return get_connection(conn_id)  # type: ignore[return-value]


def update_connection(connection_id: str, data: dict) -> dict | None:
    """Update an existing connection. Returns updated dict or None if not found."""
    existing = get_connection(connection_id)
    if not existing:
        return None
    now = datetime.now(timezone.utc)
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE connections SET
                name = :name,
                db_type = :db_type,
                host = :host,
                port = :port,
                database = :database,
                username = :username,
                password = :password,
                schema_name = :schema_name,
                ssl_enabled = :ssl_enabled,
                ssl_ca_cert = :ssl_ca_cert,
                connection_timeout = :connection_timeout,
                query_timeout = :query_timeout,
                max_pool_size = :max_pool_size,
                extra_params = :extra_params,
                selected_tables = :selected_tables,
                updated_at = :updated_at
            WHERE id = :id
        """), {
            "id": connection_id,
            "name": data.get("name", existing["name"]),
            "db_type": data.get("db_type", existing["db_type"]),
            "host": data.get("host", existing["host"]),
            "port": data.get("port", existing["port"]),
            "database": data.get("database", existing["database"]),
            "username": data.get("username", existing["username"]),
            "password": data.get("password", existing["password"]),
            "schema_name": data.get("schema_name", existing["schema_name"]),
            "ssl_enabled": data.get("ssl_enabled", existing["ssl_enabled"]),
            "ssl_ca_cert": data.get("ssl_ca_cert", existing["ssl_ca_cert"]),
            "connection_timeout": data.get("connection_timeout", existing["connection_timeout"]),
            "query_timeout": data.get("query_timeout", existing["query_timeout"]),
            "max_pool_size": data.get("max_pool_size", existing["max_pool_size"]),
            "extra_params": json.dumps(data.get("extra_params", existing["extra_params"])),
            "selected_tables": json.dumps(data.get("selected_tables")) if data.get("selected_tables") is not None else (json.dumps(existing["selected_tables"]) if existing["selected_tables"] else None),
            "updated_at": now,
        })
    return get_connection(connection_id)


def delete_connection(connection_id: str) -> bool:
    """Delete a connection. Returns True if deleted, False if not found."""
    engine = _get_engine()
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM connections WHERE id = :id"),
            {"id": connection_id},
        )
    return result.rowcount > 0


def get_selected_tables(connection_id: str) -> dict | None:
    """Get selected_tables for a connection."""
    row = get_connection(connection_id)
    if row is None:
        return None
    return row.get("selected_tables") or {}


def save_selected_tables(connection_id: str, selected_tables: dict) -> bool:
    """Update selected_tables for a connection."""
    engine = _get_engine()
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        result = conn.execute(text("""
            UPDATE connections
            SET selected_tables = :selected_tables, updated_at = :updated_at
            WHERE id = :id
        """), {
            "id": connection_id,
            "selected_tables": json.dumps(selected_tables),
            "updated_at": now,
        })
    return result.rowcount > 0


# --------------- Migration from JSON file ---------------


def migrate_from_json() -> int:
    """
    Migrate connections from the legacy connections.json file to postgres.
    Skips connections that already exist (by id). Returns count migrated.
    """
    if not _LEGACY_JSON_PATH.exists():
        return 0

    try:
        with open(_LEGACY_JSON_PATH) as f:
            data = json.load(f)
    except Exception as e:
        logger.error("failed_to_read_legacy_json", error=str(e))
        return 0

    connections = data.get("connections", [])
    if not connections:
        return 0

    migrated = 0
    for c in connections:
        existing = get_connection(c["id"])
        if existing:
            continue
        create_connection(c)
        migrated += 1

    if migrated > 0:
        logger.info("migrated_connections_from_json", count=migrated)
        # Rename the old file so it's not re-processed
        backup_path = _LEGACY_JSON_PATH.with_suffix(".json.migrated")
        try:
            _LEGACY_JSON_PATH.rename(backup_path)
            logger.info("renamed_legacy_json", old=str(_LEGACY_JSON_PATH), new=str(backup_path))
        except Exception as e:
            logger.warning("failed_to_rename_legacy_json", error=str(e))

    return migrated


# --------------- Startup ---------------


def init_connection_store() -> None:
    """Initialize the connection store: create table + migrate from JSON."""
    ensure_connections_table()
    migrate_from_json()
