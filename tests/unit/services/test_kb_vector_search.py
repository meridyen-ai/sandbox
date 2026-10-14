"""Vector search over the knowledge bases' tables (services/kb_vector_search.py).

The SQL-building tests need nothing. The search tests need a throwaway
Postgres with pgvector 0.8 and are skipped without one:

    KB_VECTOR_TEST_DB=1 SANDBOX_UPLOAD_DB_HOST=… SANDBOX_UPLOAD_DB_PORT=…
    SANDBOX_UPLOAD_DB_NAME=… SANDBOX_UPLOAD_DB_USER=… SANDBOX_UPLOAD_DB_PASSWORD=…
"""
import asyncio
import json
import os
import random

import pytest

from sandbox.services import kb_vector_search as kvs


def test_only_knowledge_base_tables_are_queried():
    sql, filtered = kvs.build_query("data_llamaindex_kb_3_e1024", file_ids=None, path_filter="")
    assert "WHERE" not in sql and not filtered
    assert ":q" in sql and ":k" in sql
    for bad in ("data_llamaindex_kb_3; DROP TABLE x", "pg_user", "data_llamaindex_kb_x"):
        with pytest.raises(ValueError):
            kvs.build_query(bad, file_ids=None, path_filter="")


def test_filters_are_bound_parameters():
    sql, filtered = kvs.build_query("data_llamaindex_kb_3", file_ids=["a'b"], path_filter="Reports/Q3")
    assert filtered
    assert "= ANY(:fids)" in sql and "LIKE :path" in sql
    assert "a'b" not in sql and "Reports" not in sql


def test_path_filter_is_a_literal_substring():
    assert kvs._like_contains("50%_off\\x") == "%50\\%\\_off\\\\x%"


def test_iterative_scan_needs_pgvector_0_8():
    assert kvs.supports_iterative_scan((0, 8, 5))
    assert kvs.supports_iterative_scan((1, 0))
    assert not kvs.supports_iterative_scan((0, 7, 4))


def test_invalidate_accepts_both_names():
    kvs._exists["data_llamaindex_kb_1"] = (False, 0.0)
    kvs.invalidate("llamaindex_kb_1")
    assert "data_llamaindex_kb_1" not in kvs._exists


needs_db = pytest.mark.skipif(not os.environ.get("KB_VECTOR_TEST_DB"), reason="needs KB_VECTOR_TEST_DB (throwaway pgvector)")
DIM = 16
TABLE = "data_llamaindex_kb_9001_e16"
ROWS = 60000  # 100 files; the filtered search below keeps two of them (2%)


def _vec(rng):
    return [rng.uniform(-1, 1) for _ in range(DIM)]


@pytest.fixture(scope="module")
def table():
    from sqlalchemy import text

    eng = kvs.get_engine()
    with eng.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        c.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        c.execute(text(f"CREATE TABLE {TABLE} (id BIGSERIAL PRIMARY KEY, text VARCHAR NOT NULL, "
                       f"metadata_ JSON, node_id VARCHAR, embedding vector({DIM}))"))
        c.execute(text("SELECT setseed(0.42)"))
        c.execute(text(f"""
            INSERT INTO {TABLE} (text, metadata_, node_id, embedding)
            SELECT 'chunk ' || i,
                   json_build_object('file_id', 'f' || (i % 100), 'doc_id', i::text,
                                     'source_path', 'Drive:/Reports/' || CASE WHEN i % 2 = 1 THEN 'Q3' ELSE 'Q4' END || '/x.pdf'),
                   'n' || i,
                   (SELECT array_agg(random() * 2 - 1) FROM generate_series(1, {DIM}) g WHERE i > 0)::vector({DIM})
            FROM generate_series(1, {ROWS}) i
        """))
        c.execute(text("SET max_parallel_maintenance_workers = 0"))
        c.execute(text("SET maintenance_work_mem = '48MB'"))
        c.execute(text(f"CREATE INDEX ON {TABLE} USING hnsw (embedding vector_cosine_ops)"))
        c.execute(text(f"ANALYZE {TABLE}"))
    kvs.invalidate()
    yield TABLE
    with eng.begin() as c:
        c.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))


@needs_db
def test_filtered_search_returns_the_full_top_k(table, monkeypatch):
    q = _vec(random.Random(99))
    rows = kvs.search_table(table, q, 20, file_ids=["f1", "f2"])
    assert len(rows) == 20
    assert {r.metadata["file_id"] for r in rows} <= {"f1", "f2"}
    assert [r.similarity for r in rows] == sorted((r.similarity for r in rows), reverse=True)
    # Without the iterative scan the index stops after ef_search candidates and
    # the filter leaves only the few of them that belong to the two files.
    monkeypatch.setattr(kvs, "supports_iterative_scan", lambda v: False)
    short = kvs.search_table(table, q, 20, file_ids=["f1", "f2"])
    assert len(short) < 20


@needs_db
def test_unfiltered_path_filter_and_missing_table(table):
    q = _vec(random.Random(5))
    assert len(kvs.search_table(table, q, 10)) == 10
    rows = kvs.search_table(table, q, 10, path_filter="/Reports/Q3/")
    assert len(rows) == 10 and all("/Q3/" in r.metadata["source_path"] for r in rows)
    assert kvs.search_table("data_llamaindex_kb_424242", q, 10) == []


@needs_db
def test_several_tables_at_once(table):
    q = _vec(random.Random(11))
    pairs = asyncio.run(kvs.search_tables([(1, table), (2, "data_llamaindex_kb_424242"), (3, table)], q, 5))
    assert len(pairs) == 10
    assert {k for k, _ in pairs} == {1, 3}
