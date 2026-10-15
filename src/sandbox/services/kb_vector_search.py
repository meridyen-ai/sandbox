"""Nearest-neighbour search over the knowledge bases' vector tables.

The query endpoint used to build a LlamaIndex ``PGVectorStore`` for every
knowledge base on every request: a new SQLAlchemy engine (and connection pool)
each time, the knowledge bases searched one after another, and filters that
LlamaIndex writes into the SQL as literals (``file_id IN ('…')``), with
``CONTAINS`` meaning JSON-array containment, so a ``source_path`` filter never
matched a path at all.

Here one engine and pool serve every query; a table's existence is cached
per knowledge base and dropped when the indexing path writes to it
(``invalidate``); knowledge bases are searched at the same time, each with a
timeout; every value is a bound parameter. Filtered searches turn on pgvector
0.8's iterative index scan (``hnsw.iterative_scan = relaxed_order``) so a
filter that removes most of the first candidates still returns the full top-k
instead of a short list.

Rows are the tables LlamaIndex writes (``data_llamaindex_kb_<id>[_e<dim>]``:
``node_id, text, metadata_, embedding``); the caller turns a row's metadata
back into a node the same way PGVectorStore does.
"""
from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

logger = structlog.get_logger(__name__)

_TABLE = re.compile(r"^data_llamaindex_kb_\d+(?:_e\d+(?:_c\d+)?)?$")


def _env_int(name: str, default: int, *, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


EF_SEARCH = _env_int("VECTOR_HNSW_EF_SEARCH", 40, lo=10, hi=1000)
# A filtered search visits more of the graph before it gives up.
EF_SEARCH_FILTERED = _env_int("VECTOR_HNSW_EF_SEARCH_FILTERED", 100, lo=10, hi=1000)
QUERY_TIMEOUT_MS = _env_int("VECTOR_QUERY_TIMEOUT_MS", 15000, lo=500, hi=120000)
NEGATIVE_TTL_SECONDS = 30.0

# ── one engine for every query ───────────────────────────────────────────────

_engine = None
_engine_lock = threading.Lock()


def get_engine():
    """The pooled engine vector queries share (sized for parallel knowledge
    bases and concurrent questions)."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from sqlalchemy import create_engine

                host = os.environ.get("SANDBOX_UPLOAD_DB_HOST", "sandbox-postgres")
                port = int(os.environ.get("SANDBOX_UPLOAD_DB_PORT", "5432"))
                db = os.environ.get("SANDBOX_UPLOAD_DB_NAME", "sandbox_uploads")
                user = os.environ.get("SANDBOX_UPLOAD_DB_USER", "sandbox")
                password = os.environ.get("SANDBOX_UPLOAD_DB_PASSWORD", "sandbox_password")
                from sqlalchemy.engine import URL

                url = URL.create("postgresql+psycopg2", username=user, password=password,
                                 host=host, port=port, database=db)
                _engine = create_engine(
                    url,
                    pool_pre_ping=True,
                    pool_size=_env_int("VECTOR_QUERY_POOL_SIZE", 8, lo=1, hi=64),
                    max_overflow=_env_int("VECTOR_QUERY_POOL_OVERFLOW", 4, lo=0, hi=64),
                    pool_recycle=1800,
                    pool_timeout=10,
                    connect_args={"connect_timeout": 10},
                )
    return _engine


# ── per-table cache ──────────────────────────────────────────────────────────

_exists: Dict[str, Tuple[bool, float]] = {}
_exists_lock = threading.Lock()
_vector_version: Optional[Tuple[int, ...]] = None


def invalidate(table: Optional[str] = None) -> None:
    """Forget what is known about ``table`` (``data_…`` or the LlamaIndex
    name without the prefix), or about every table."""
    with _exists_lock:
        if table is None:
            _exists.clear()
        else:
            _exists.pop(table if table.startswith("data_") else f"data_{table}", None)


def _table_exists(conn, table: str) -> bool:
    from sqlalchemy import text

    now = time.monotonic()
    with _exists_lock:
        known = _exists.get(table)
    if known is not None and (known[0] or now - known[1] < NEGATIVE_TTL_SECONDS):
        return known[0]
    present = bool(conn.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}).scalar())
    with _exists_lock:
        _exists[table] = (present, now)
    return present


def first_existing(tables: Sequence[str]) -> str:
    """The first of ``tables`` that exists (the last one when none does): a
    vector table of new chunk settings, until it is filled, falls back to the
    current one (services/chunking.py)."""
    if len(tables) == 1:
        return tables[0]
    with get_engine().connect() as conn:
        for t in tables:
            if _table_exists(conn, t):
                return t
    return tables[-1]


def _pgvector_version(conn) -> Tuple[int, ...]:
    global _vector_version
    if _vector_version is None:
        from sqlalchemy import text

        v = conn.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar() or "0"
        _vector_version = tuple(int(p) for p in re.findall(r"\d+", v)[:3]) or (0,)
    return _vector_version


def supports_iterative_scan(version: Sequence[int]) -> bool:
    return tuple(version) >= (0, 8, 0)


# ── the query ────────────────────────────────────────────────────────────────

@dataclass
class VectorRow:
    node_id: str
    text: str
    metadata: Dict[str, Any]
    similarity: float


def vector_literal(embedding: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


def _like_contains(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def build_query(table: str, *, file_ids: Optional[Sequence[str]], path_filter: str) -> Tuple[str, bool]:
    """The SQL for one table and whether it is filtered. Values are bound
    parameters (:q, :k, :fids, :path); the table name is checked."""
    if not _TABLE.match(table):
        raise ValueError(f"not a knowledge-base vector table: {table!r}")
    where = []
    if file_ids:
        where.append("metadata_->>'file_id' = ANY(:fids)")
    if path_filter:
        where.append("metadata_->>'source_path' LIKE :path ESCAPE '\\'")
    sql = (
        f"SELECT node_id, text, metadata_, embedding <=> CAST(:q AS vector) AS distance FROM {table} "
        + (f"WHERE {' AND '.join(where)} " if where else "")
        + "ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
    )
    return sql, bool(where)


def search_table(table: str, embedding: Sequence[float], top_k: int, *,
                 file_ids: Optional[Sequence[str]] = None, path_filter: str = "") -> List[VectorRow]:
    """The ``top_k`` nearest rows of one table, nearest first."""
    from sqlalchemy import text

    sql, filtered = build_query(table, file_ids=file_ids, path_filter=path_filter)
    params: Dict[str, Any] = {"q": vector_literal(embedding), "k": int(top_k)}
    if file_ids:
        params["fids"] = [str(f) for f in file_ids]
    if path_filter:
        params["path"] = _like_contains(path_filter)
    with get_engine().begin() as conn:
        if not _table_exists(conn, table):
            return []
        settings = {
            "statement_timeout": f"{QUERY_TIMEOUT_MS}ms",
            "hnsw.ef_search": str(max(EF_SEARCH_FILTERED if filtered else EF_SEARCH, int(top_k))),
        }
        if filtered and supports_iterative_scan(_pgvector_version(conn)):
            settings["hnsw.iterative_scan"] = "relaxed_order"
        for name, value in settings.items():
            # Transaction-local (is_local = true): nothing leaks into the pool.
            conn.execute(text("SELECT set_config(:n, :v, true)"), {"n": name, "v": value})
        rows = conn.execute(text(sql), params).fetchall()
    out = []
    for r in rows:
        meta = r.metadata_
        if isinstance(meta, str):
            import json

            meta = json.loads(meta)
        out.append(VectorRow(node_id=r.node_id, text=r.text or "", metadata=meta or {},
                             similarity=1.0 - float(r.distance) if r.distance is not None else 0.0))
    # relaxed_order may hand rows back slightly out of order.
    out.sort(key=lambda row: -row.similarity)
    return out


async def search_tables(tables: Sequence[Tuple[Any, str]], embedding: Sequence[float], top_k: int, *,
                        file_ids: Optional[Sequence[str]] = None, path_filter: str = "",
                        timeout: float = QUERY_TIMEOUT_MS / 1000 + 2) -> List[Tuple[Any, VectorRow]]:
    """Every (key, table) searched at the same time; a table that fails or
    times out is logged and skipped. Returns (key, row) pairs, nearest first."""

    async def one(key, table):
        started = time.monotonic()
        try:
            rows = await asyncio.wait_for(
                asyncio.to_thread(search_table, table, embedding, top_k, file_ids=file_ids, path_filter=path_filter),
                timeout,
            )
        except Exception as e:  # noqa: BLE001 — the other knowledge bases still answer
            logger.warning("kb_query_failed", table=table, error=str(e)[:200] or type(e).__name__)
            return []
        logger.info("kb_query", table=table, rows=len(rows), ms=round((time.monotonic() - started) * 1000))
        return [(key, row) for row in rows]

    results = await asyncio.gather(*(one(key, table) for key, table in tables))
    merged = [pair for part in results for pair in part]
    merged.sort(key=lambda pair: -pair[1].similarity)
    return merged


def row_to_node(row: VectorRow):
    """A LlamaIndex node from a row, exactly as PGVectorStore rebuilds one."""
    from llama_index.core.schema import TextNode
    from llama_index.core.vector_stores.utils import metadata_dict_to_node

    try:
        node = metadata_dict_to_node(row.metadata)
        node.set_content(str(row.text))
    except Exception:  # noqa: BLE001 — rows written before node metadata existed
        node = TextNode(id_=row.node_id, text=row.text, metadata=row.metadata)
    return node
