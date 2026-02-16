"""
File-to-PostgreSQL Loader

Loads CSV and Excel file data into the sandbox PostgreSQL database,
so uploaded data can be queried via standard SQL instead of pandas.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from sandbox.core.logging import get_logger

logger = get_logger(__name__)

# Upload database connection defaults (overridden by env vars)
_UPLOAD_DB_HOST = os.environ.get("SANDBOX_UPLOAD_DB_HOST", "sandbox-postgres")
_UPLOAD_DB_PORT = int(os.environ.get("SANDBOX_UPLOAD_DB_PORT", "5432"))
_UPLOAD_DB_NAME = os.environ.get("SANDBOX_UPLOAD_DB_NAME", "sandbox_uploads")
_UPLOAD_DB_USER = os.environ.get("SANDBOX_UPLOAD_DB_USER", "sandbox")
_UPLOAD_DB_PASSWORD = os.environ.get("SANDBOX_UPLOAD_DB_PASSWORD", "sandbox_password")

UPLOADS_SCHEMA = "uploads"

# Chunk size for loading large files (rows per batch)
LOAD_CHUNK_SIZE = 50_000

_engine: Engine | None = None


def get_upload_engine() -> Engine:
    """Get or create SQLAlchemy engine for the upload database."""
    global _engine
    if _engine is None:
        url = (
            f"postgresql+psycopg2://{_UPLOAD_DB_USER}:{_UPLOAD_DB_PASSWORD}"
            f"@{_UPLOAD_DB_HOST}:{_UPLOAD_DB_PORT}/{_UPLOAD_DB_NAME}"
        )
        _engine = create_engine(url, pool_pre_ping=True, pool_size=5)
        logger.info(
            "upload_engine_created",
            host=_UPLOAD_DB_HOST,
            database=_UPLOAD_DB_NAME,
        )
    return _engine


def get_upload_db_config() -> dict[str, Any]:
    """Return connection config dict for the upload database."""
    return {
        "host": _UPLOAD_DB_HOST,
        "port": _UPLOAD_DB_PORT,
        "database": _UPLOAD_DB_NAME,
        "username": _UPLOAD_DB_USER,
        "password": _UPLOAD_DB_PASSWORD,
        "schema": UPLOADS_SCHEMA,
    }


def sanitize_table_name(name: str) -> str:
    """Convert a user-provided name into a safe SQL table identifier.

    - Lowercase
    - Only alphanumeric and underscores
    - Prefix with 't_' if starts with a digit
    - Truncate to 63 chars (PostgreSQL limit)
    """
    clean = re.sub(r"[^a-z0-9_]", "_", name.lower().strip())
    clean = re.sub(r"_+", "_", clean).strip("_")
    if not clean:
        clean = "uploaded_data"
    if clean[0].isdigit():
        clean = f"t_{clean}"
    return clean[:63]


def ensure_uploads_schema(engine: Engine) -> None:
    """Create the uploads schema if it doesn't exist."""
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {UPLOADS_SCHEMA}"))
        conn.commit()
    logger.debug("uploads_schema_ensured", schema=UPLOADS_SCHEMA)


def load_csv_to_postgres(
    file_path: str,
    table_name: str,
    delimiter: str = ",",
    has_header: bool = True,
    engine: Engine | None = None,
) -> dict[str, Any]:
    """Load a CSV file into the upload database.

    Returns dict with row_count and column_count.
    Uses chunked reading for large files to limit memory usage.
    """
    engine = engine or get_upload_engine()
    ensure_uploads_schema(engine)

    safe_table = sanitize_table_name(table_name)

    # Read in chunks for memory efficiency
    reader = pd.read_csv(
        file_path,
        sep=delimiter,
        header=0 if has_header else None,
        chunksize=LOAD_CHUNK_SIZE,
    )

    total_rows = 0
    column_count = 0
    first_chunk = True

    for chunk in reader:
        # Sanitize column names for PostgreSQL
        chunk.columns = [
            sanitize_table_name(str(c)) if has_header else f"col_{i}"
            for i, c in enumerate(chunk.columns)
        ]
        column_count = len(chunk.columns)

        chunk.to_sql(
            safe_table,
            engine,
            schema=UPLOADS_SCHEMA,
            if_exists="replace" if first_chunk else "append",
            index=False,
            method="multi",
        )
        total_rows += len(chunk)
        first_chunk = False

    logger.info(
        "csv_loaded_to_postgres",
        table=f"{UPLOADS_SCHEMA}.{safe_table}",
        rows=total_rows,
        columns=column_count,
    )

    return {
        "table_name": safe_table,
        "row_count": total_rows,
        "column_count": column_count,
    }


def load_excel_sheet_to_postgres(
    file_path: str,
    sheet_name: str,
    table_name: str,
    has_header: bool = True,
    engine: Engine | None = None,
) -> dict[str, Any]:
    """Load a single Excel sheet into the upload database.

    Returns dict with row_count and column_count.
    """
    engine = engine or get_upload_engine()
    ensure_uploads_schema(engine)

    safe_table = sanitize_table_name(table_name)
    file_ext = Path(file_path).suffix.lower()
    excel_engine = "openpyxl" if file_ext == ".xlsx" else "xlrd"

    df = pd.read_excel(
        file_path,
        sheet_name=sheet_name,
        header=0 if has_header else None,
        engine=excel_engine,
    )

    if df.empty:
        return {"table_name": safe_table, "row_count": 0, "column_count": 0}

    # Sanitize column names
    df.columns = [
        sanitize_table_name(str(c)) if has_header else f"col_{i}"
        for i, c in enumerate(df.columns)
    ]

    # Load in chunks for large sheets
    total_rows = len(df)
    column_count = len(df.columns)

    if total_rows <= LOAD_CHUNK_SIZE:
        df.to_sql(
            safe_table,
            engine,
            schema=UPLOADS_SCHEMA,
            if_exists="replace",
            index=False,
            method="multi",
        )
    else:
        for i in range(0, total_rows, LOAD_CHUNK_SIZE):
            chunk = df.iloc[i : i + LOAD_CHUNK_SIZE]
            chunk.to_sql(
                safe_table,
                engine,
                schema=UPLOADS_SCHEMA,
                if_exists="replace" if i == 0 else "append",
                index=False,
                method="multi",
            )

    logger.info(
        "excel_sheet_loaded_to_postgres",
        table=f"{UPLOADS_SCHEMA}.{safe_table}",
        sheet=sheet_name,
        rows=total_rows,
        columns=column_count,
    )

    return {
        "table_name": safe_table,
        "row_count": total_rows,
        "column_count": column_count,
    }


def drop_upload_table(table_name: str, engine: Engine | None = None) -> None:
    """Drop an uploaded table from the uploads schema."""
    engine = engine or get_upload_engine()
    safe_table = sanitize_table_name(table_name)
    with engine.connect() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {UPLOADS_SCHEMA}.{safe_table}"))
        conn.commit()
    logger.info("upload_table_dropped", table=f"{UPLOADS_SCHEMA}.{safe_table}")
