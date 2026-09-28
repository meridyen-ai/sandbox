"""Re-embed legacy (OpenAI, 1536-dim) KB vectors with the local model.

    python -m sandbox.services.kb_reembed            # every KB
    python -m sandbox.services.kb_reembed --kb 14    # one KB

Indexing moved from text-embedding-3-small to the local model, whose vectors
live in their own table (see `_kb_vector_table` in rest_api). Chunks indexed
before the switch exist only in the legacy table, which a local-model query
cannot search. This copies each legacy chunk — same text, metadata and node_id,
so citations and neighbour lookups are unchanged — and embeds it locally.

Needs no source files and no API key. Idempotent and resumable: a chunk already
present in the local table (by node_id) is skipped, so re-running after an
interruption, or after new uploads, only does the remaining work. The legacy
tables are left untouched.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time

from sqlalchemy import create_engine, text as sql_text
from sqlalchemy.engine import URL

from sandbox.services import local_embedder

LEGACY_TABLE = re.compile(r"^data_llamaindex_kb_(\d+)$")
#: Rows embedded + committed together — the unit of work lost on an interrupt.
COMMIT_ROWS = 64


def _db_params() -> dict:
    return {
        "host": os.environ.get("SANDBOX_UPLOAD_DB_HOST", "sandbox-postgres"),
        "port": os.environ.get("SANDBOX_UPLOAD_DB_PORT", "5432"),
        "database": os.environ.get("SANDBOX_UPLOAD_DB_NAME", "sandbox_uploads"),
        "user": os.environ.get("SANDBOX_UPLOAD_DB_USER", "sandbox"),
        "password": os.environ.get("SANDBOX_UPLOAD_DB_PASSWORD", "sandbox_password"),
    }


def _ensure_local_table(kb_id: int, dim: int) -> str:
    """Create the local-model table exactly as the indexing path would, so the
    two never disagree on schema or ANN index."""
    from llama_index.vector_stores.postgres import PGVectorStore

    name = f"llamaindex_kb_{kb_id}_e{dim}"
    PGVectorStore.from_params(
        **_db_params(),
        table_name=name,
        embed_dim=dim,
        hnsw_kwargs={
            "hnsw_m": int(os.environ.get("VECTOR_HNSW_M", "16")),
            "hnsw_ef_construction": int(os.environ.get("VECTOR_HNSW_EF_CONSTRUCTION", "64")),
            "hnsw_ef_search": int(os.environ.get("VECTOR_HNSW_EF_SEARCH", "40")),
            "hnsw_dist_method": "vector_cosine_ops",
        },
    ).add([])  # no nodes: initialises table + HNSW index only
    return f"data_{name}"


def reembed_kb(engine, kb_id: int) -> int:
    dim = local_embedder.EMBEDDING_DIMENSIONS
    legacy = f"data_llamaindex_kb_{kb_id}"
    target = _ensure_local_table(kb_id, dim)

    with engine.begin() as c:
        c.execute(sql_text(
            f"CREATE INDEX IF NOT EXISTS idx_{target[5:]}_file_id "
            f"ON {target} ((metadata_->>'file_id'))"
        ))
    with engine.connect() as c:
        todo = c.execute(sql_text(
            f"SELECT l.id FROM {legacy} l "
            f"WHERE NOT EXISTS (SELECT 1 FROM {target} t WHERE t.node_id = l.node_id) "
            f"ORDER BY l.id"
        )).scalars().all()
    print(f"kb {kb_id}: {len(todo)} chunk(s) to embed", flush=True)

    done, started = 0, time.time()
    for i in range(0, len(todo), COMMIT_ROWS):
        ids = todo[i:i + COMMIT_ROWS]
        with engine.begin() as c:
            rows = c.execute(
                sql_text(f"SELECT text, metadata_, node_id FROM {legacy} WHERE id = ANY(:ids) ORDER BY id"),
                {"ids": ids},
            ).fetchall()
            vectors = local_embedder.embed_texts([r[0] for r in rows])
            c.execute(
                sql_text(
                    f"INSERT INTO {target} (text, metadata_, node_id, embedding) "
                    f"VALUES (:text, CAST(:meta AS json), :node_id, CAST(:emb AS vector))"
                ),
                [
                    {
                        "text": r[0],
                        "meta": json.dumps(r[1]) if not isinstance(r[1], str) else r[1],
                        "node_id": r[2],
                        "emb": "[" + ",".join(map(str, v)) + "]",
                    }
                    for r, v in zip(rows, vectors)
                ],
            )
        done += len(rows)
        rate = done / max(time.time() - started, 1e-6)
        print(f"kb {kb_id}: {done}/{len(todo)} ({rate:.1f} chunks/s)", flush=True)
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kb", type=int, action="append", help="KB id (repeatable); default: all")
    args = parser.parse_args()

    p = _db_params()
    engine = create_engine(URL.create(
        "postgresql+psycopg2", username=p["user"], password=p["password"],
        host=p["host"], port=int(p["port"]), database=p["database"],
    ))
    with engine.connect() as c:
        tables = c.execute(sql_text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND tablename LIKE 'data_llamaindex_kb_%'"
        )).scalars().all()
    kb_ids = sorted(int(m.group(1)) for m in map(LEGACY_TABLE.match, tables) if m)
    if args.kb:
        kb_ids = [k for k in kb_ids if k in set(args.kb)]

    total = sum(reembed_kb(engine, kb_id) for kb_id in kb_ids)
    print(f"done: {total} chunk(s) embedded across {len(kb_ids)} KB(s)", flush=True)


if __name__ == "__main__":
    main()
