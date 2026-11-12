"""File uploads load into PostgreSQL on a worker thread, not on the event loop.

No network and no Postgres: the per-upload database is a SQLite file (pandas
``to_sql`` is generic SQLAlchemy), and the sandbox's connection store is a
recorder. Pins:
  * while a (slow, faked) load runs, /health is answered at once;
  * what the upload routes answer and leave behind for a small CSV, a small
    two-sheet XLSX and the error cases is what they answered before (status,
    body, rows loaded, the connection registered, the source file removed).
Runs under pytest, or directly: `python /xtests/test_upload_threadpool.py`.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
from fastapi import FastAPI
from sqlalchemy import create_engine

from sandbox.core import connection_store
from sandbox.core.config import get_config
from sandbox.services import file_loader, rest_api

# Recorded from the routes as they were before the load moved to a worker thread
# (this file run against that code). Connection ids are replaced by <uuid>.
EXPECTED = json.loads(r'''{
 "connections": [
  {
   "connection_timeout": 30,
   "database": "upload_1",
   "db_type": "postgresql",
   "extra_params": {},
   "host": "fake-host",
   "id": "<uuid>",
   "max_pool_size": 10,
   "name": "Sales Data",
   "password": "**********",
   "port": 5432,
   "query_timeout": 300,
   "schema_name": null,
   "selected_tables": null,
   "ssl_ca_cert": null,
   "ssl_enabled": false,
   "ssl_mode": null,
   "username": "u"
  },
  {
   "connection_timeout": 30,
   "database": "upload_2",
   "db_type": "postgresql",
   "extra_params": {},
   "host": "fake-host",
   "id": "<uuid>",
   "max_pool_size": 10,
   "name": "semi",
   "password": "**********",
   "port": 5432,
   "query_timeout": 300,
   "schema_name": null,
   "selected_tables": null,
   "ssl_ca_cert": null,
   "ssl_enabled": false,
   "ssl_mode": null,
   "username": "u"
  },
  {
   "connection_timeout": 30,
   "database": "upload_3",
   "db_type": "postgresql",
   "extra_params": {},
   "host": "fake-host",
   "id": "<uuid>",
   "max_pool_size": 10,
   "name": "Book",
   "password": "**********",
   "port": 5432,
   "query_timeout": 300,
   "schema_name": null,
   "selected_tables": null,
   "ssl_ca_cert": null,
   "ssl_enabled": false,
   "ssl_mode": null,
   "username": "u"
  },
  {
   "connection_timeout": 30,
   "database": "upload_4",
   "db_type": "postgresql",
   "extra_params": {},
   "host": "fake-host",
   "id": "<uuid>",
   "max_pool_size": 10,
   "name": "Book2",
   "password": "**********",
   "port": 5432,
   "query_timeout": 300,
   "schema_name": null,
   "selected_tables": null,
   "ssl_ca_cert": null,
   "ssl_enabled": false,
   "ssl_mode": null,
   "username": "u"
  },
  {
   "connection_timeout": 30,
   "database": "upload_8",
   "db_type": "postgresql",
   "extra_params": {},
   "host": "fake-host",
   "id": "<uuid>",
   "max_pool_size": 10,
   "name": "conn doc_csv",
   "password": "**********",
   "port": 5432,
   "query_timeout": 300,
   "schema_name": null,
   "selected_tables": null,
   "ssl_ca_cert": null,
   "ssl_enabled": false,
   "ssl_mode": null,
   "username": "u"
  },
  {
   "connection_timeout": 30,
   "database": "upload_9",
   "db_type": "postgresql",
   "extra_params": {},
   "host": "fake-host",
   "id": "<uuid>",
   "max_pool_size": 10,
   "name": "conn doc_xlsx",
   "password": "**********",
   "port": 5432,
   "query_timeout": 300,
   "schema_name": null,
   "selected_tables": null,
   "ssl_ca_cert": null,
   "ssl_enabled": false,
   "ssl_mode": null,
   "username": "u"
  }
 ],
 "databases": {
  "upload_1.db": {
   "sales_data": [
    [
     1,
     "ali",
     10.5
    ],
    [
     2,
     "veli",
     20.0
    ],
    [
     3,
     "ayse",
     null
    ]
   ]
  },
  "upload_10.db": {},
  "upload_2.db": {
   "semi": [
    [
     1,
     "a"
    ],
    [
     2,
     "b"
    ]
   ]
  },
  "upload_3.db": {
   "book_cities": [
    [
     "a",
     1
    ],
    [
     "b",
     2
    ]
   ],
   "book_stock": [
    [
     "x",
     5
    ]
   ]
  },
  "upload_4.db": {
   "book2": [
    [
     "x",
     5
    ]
   ]
  },
  "upload_5.db": {},
  "upload_6.db": {
   "empty": []
  },
  "upload_7.db": {},
  "upload_8.db": {
   "orders": [
    [
     1,
     "ali",
     10.5
    ],
    [
     2,
     "veli",
     20.0
    ],
    [
     3,
     "ayse",
     null
    ]
   ]
  },
  "upload_9.db": {
   "book_cities": [
    [
     "a",
     1
    ],
    [
     "b",
     2
    ]
   ],
   "book_stock": [
    [
     "x",
     5
    ]
   ]
  }
 },
 "registered": [
  {
   "database": "upload_1",
   "db_type": "postgresql",
   "host": "fake-host",
   "id": "<uuid>",
   "name": "Sales Data",
   "password": "p",
   "port": 5432,
   "ssl_enabled": false,
   "username": "u"
  },
  {
   "database": "upload_2",
   "db_type": "postgresql",
   "host": "fake-host",
   "id": "<uuid>",
   "name": "semi",
   "password": "p",
   "port": 5432,
   "ssl_enabled": false,
   "username": "u"
  },
  {
   "database": "upload_3",
   "db_type": "postgresql",
   "host": "fake-host",
   "id": "<uuid>",
   "name": "Book",
   "password": "p",
   "port": 5432,
   "ssl_enabled": false,
   "username": "u"
  },
  {
   "database": "upload_4",
   "db_type": "postgresql",
   "host": "fake-host",
   "id": "<uuid>",
   "name": "Book2",
   "password": "p",
   "port": 5432,
   "ssl_enabled": false,
   "username": "u"
  },
  {
   "database": "upload_8",
   "db_type": "postgresql",
   "host": "fake-host",
   "id": "<uuid>",
   "name": "conn doc_csv",
   "password": "p",
   "port": 5432,
   "ssl_enabled": false,
   "username": "u"
  },
  {
   "database": "upload_9",
   "db_type": "postgresql",
   "host": "fake-host",
   "id": "<uuid>",
   "name": "conn doc_xlsx",
   "password": "p",
   "port": 5432,
   "ssl_enabled": false,
   "username": "u"
  }
 ],
 "responses": {
  "bad_extension": [
   400,
   {
    "detail": "Unsupported file type '.txt'. Allowed: CSV, XLSX, XLS"
   }
  ],
  "corrupt_xlsx": [
   400,
   {
    "detail": "Failed to load file into database: File is not a zip file"
   }
  ],
  "csv": [
   201,
   {
    "column_count": 3,
    "connection_id": "<uuid>",
    "database": "upload_1",
    "db_type": "csv",
    "host": "fake-host",
    "message": "CSV loaded into PostgreSQL: 3 rows, 3 columns",
    "name": "Sales Data",
    "port": 5432,
    "row_count": 3,
    "source_type": "csv",
    "success": true,
    "table_name": "sales_data",
    "upload_tables": [
     "sales_data"
    ]
   }
  ],
  "csv_empty": [
   400,
   {
    "detail": "CSV file is empty"
   }
  ],
  "csv_semicolon_no_header": [
   201,
   {
    "column_count": 2,
    "connection_id": "<uuid>",
    "database": "upload_2",
    "db_type": "csv",
    "host": "fake-host",
    "message": "CSV loaded into PostgreSQL: 2 rows, 2 columns",
    "name": "semi",
    "port": 5432,
    "row_count": 2,
    "source_type": "csv",
    "success": true,
    "table_name": "semi",
    "upload_tables": [
     "semi"
    ]
   }
  ],
  "doc_bad_type": [
   400,
   {
    "detail": "Unsupported spreadsheet type '.pdf'. Allowed: CSV, XLSX, XLS"
   }
  ],
  "doc_csv": [
   201,
   {
    "connection_id": "<uuid>",
    "database": "upload_8",
    "host": "fake-host",
    "name": "conn doc_csv",
    "port": 5432,
    "status": "ready",
    "success": true,
    "tables": [
     {
      "column_count": 3,
      "row_count": 3,
      "sheet_name": null,
      "table_name": "orders"
     }
    ],
    "total_rows": 3,
    "total_tables": 1
   }
  ],
  "doc_csv_stored": [
   200,
   {
    "filename": "orders.csv",
    "folder_path": "reports"
   }
  ],
  "doc_missing": [
   404,
   {
    "detail": "File <uuid> not found in sandbox storage"
   }
  ],
  "doc_xlsx": [
   201,
   {
    "connection_id": "<uuid>",
    "database": "upload_9",
    "host": "fake-host",
    "name": "conn doc_xlsx",
    "port": 5432,
    "status": "ready",
    "success": true,
    "tables": [
     {
      "column_count": 2,
      "row_count": 2,
      "sheet_name": "Cities",
      "table_name": "book_cities"
     },
     {
      "column_count": 2,
      "row_count": 1,
      "sheet_name": "Stock",
      "table_name": "book_stock"
     }
    ],
    "total_rows": 3,
    "total_tables": 2
   }
  ],
  "doc_xlsx_blank": [
   400,
   {
    "detail": "All sheets are empty"
   }
  ],
  "doc_xlsx_blank_stored": [
   200,
   {
    "filename": "blank.xlsx",
    "folder_path": "reports"
   }
  ],
  "doc_xlsx_stored": [
   200,
   {
    "filename": "book.xlsx",
    "folder_path": "reports"
   }
  ],
  "xlsx_one_sheet_chosen": [
   201,
   {
    "connection_id": "<uuid>",
    "connections": [
     {
      "connection_id": "<uuid>",
      "name": "Book2",
      "row_count": 1,
      "sheet_name": "Stock",
      "table_name": "book2"
     }
    ],
    "database": "upload_4",
    "db_type": "csv",
    "host": "fake-host",
    "message": "Excel file loaded into PostgreSQL: 1 sheet(s), 1 total rows",
    "name": "Book2",
    "port": 5432,
    "row_count": 1,
    "sheet_stats": [
     {
      "column_count": 2,
      "row_count": 1,
      "sheet_name": "Stock",
      "table_name": "book2"
     }
    ],
    "sheets": [
     "Cities",
     "Stock",
     "Blank"
    ],
    "source_type": "excel",
    "success": true,
    "upload_tables": [
     "book2"
    ]
   }
  ],
  "xlsx_two_sheets": [
   201,
   {
    "connection_id": "<uuid>",
    "connections": [
     {
      "connection_id": "<uuid>",
      "name": "Book - Cities",
      "row_count": 2,
      "sheet_name": "Cities",
      "table_name": "book_cities"
     },
     {
      "connection_id": "<uuid>",
      "name": "Book - Stock",
      "row_count": 1,
      "sheet_name": "Stock",
      "table_name": "book_stock"
     }
    ],
    "database": "upload_3",
    "db_type": "csv",
    "host": "fake-host",
    "message": "Excel file loaded into PostgreSQL: 2 sheet(s), 3 total rows",
    "name": "Book",
    "port": 5432,
    "row_count": 3,
    "sheet_stats": [
     {
      "column_count": 2,
      "row_count": 2,
      "sheet_name": "Cities",
      "table_name": "book_cities"
     },
     {
      "column_count": 2,
      "row_count": 1,
      "sheet_name": "Stock",
      "table_name": "book_stock"
     }
    ],
    "sheets": [
     "Cities",
     "Stock",
     "Blank"
    ],
    "source_type": "excel",
    "success": true,
    "upload_tables": [
     "book_cities",
     "book_stock"
    ]
   }
  ],
  "xlsx_unknown_sheet": [
   400,
   {
    "detail": "Sheet(s) not found: Nope. Available: Cities, Stock, Blank"
   }
  ]
 },
 "uploads_left_behind": []
}''')

_WORK = tempfile.mkdtemp(prefix="ss-sandbox-upload-")
_APP = None
_STATE = {"dbs": [], "registered": []}


def _app():
    global _APP
    if _APP is None:
        app = FastAPI()
        app.state.start_time = datetime.now(timezone.utc)
        rest_api.register_routes(app)
        app.dependency_overrides[rest_api.verify_sandbox_token] = lambda: {
            "space_id": "default", "user_id": "u1", "auth_type": "api_key",
        }
        _APP = app
    return _APP


def _fake_create_upload_database(upload_name, reuse=None):
    path = os.path.join(_WORK, f"upload_{len(_STATE['dbs']) + 1}.db")
    _STATE["dbs"].append(path)
    config = {"host": "fake-host", "port": 5432, "database": f"upload_{len(_STATE['dbs'])}",
              "username": "u", "password": "p"}
    return create_engine(f"sqlite:///{path}"), config


def _install(monkeypatch, load_csv=None):
    _STATE["dbs"].clear()
    _STATE["registered"].clear()
    monkeypatch.setattr(file_loader, "create_upload_database", _fake_create_upload_database)
    monkeypatch.setattr(connection_store, "create_connection",
                        lambda data: _STATE["registered"].append(data) or data)
    if load_csv is not None:
        monkeypatch.setattr(file_loader, "load_csv_to_postgres", load_csv)
    get_config().database_connections.clear()


def _csv_bytes():
    return b"Id,Name,Amount\n1,ali,10.5\n2,veli,20\n3,ayse,\n"


def _xlsx_bytes():
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        pd.DataFrame({"City": ["a", "b"], "Pop": [1, 2]}).to_excel(w, sheet_name="Cities", index=False)
        pd.DataFrame({"Item": ["x"], "Qty": [5]}).to_excel(w, sheet_name="Stock", index=False)
        pd.DataFrame({"Empty": []}).to_excel(w, sheet_name="Blank", index=False)
    return buf.getvalue()


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://t")


def _norm(obj):
    """Drop what is random per call (uuids)."""
    text = json.dumps(obj, sort_keys=True)
    text = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>", text)
    return json.loads(text)


def _db_contents():
    out = {}
    for path in _STATE["dbs"]:
        con = sqlite3.connect(path)
        try:
            names = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by 1")]
            out[os.path.basename(path)] = {n: con.execute(f'select * from "{n}"').fetchall() for n in names}
        finally:
            con.close()
    return out


def _uploads_dir_listing():
    d = Path("/app/data/uploads")
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


# --------------------------------------------------------------- outcomes ---

async def _run_table():
    results = {}
    async with _client() as c:
        async def upload(label, filename, content, **form):
            data = {"name": "Sales Data", "delimiter": ",", "has_header": "true", "selected_sheets": ""}
            data.update(form)
            r = await c.post("/api/v1/upload-file", files={"file": (filename, content)}, data=data)
            results[label] = [r.status_code, r.json()]

        await upload("csv", "sales.csv", _csv_bytes())
        await upload("csv_semicolon_no_header", "s.csv", b"1;a\n2;b\n", delimiter=";", has_header="false", name="semi")
        await upload("xlsx_two_sheets", "book.xlsx", _xlsx_bytes(), name="Book")
        await upload("xlsx_one_sheet_chosen", "book.xlsx", _xlsx_bytes(), name="Book2", selected_sheets="Stock")
        await upload("xlsx_unknown_sheet", "book.xlsx", _xlsx_bytes(), name="Book3", selected_sheets="Nope")
        await upload("csv_empty", "e.csv", b"a,b\n", name="empty")
        await upload("bad_extension", "x.txt", b"hello")
        await upload("corrupt_xlsx", "bad.xlsx", b"not a workbook", name="corrupt")

        # documents: store, then load as tables
        for label, filename, content in (("doc_csv", "orders.csv", _csv_bytes()), ("doc_xlsx", "book.xlsx", _xlsx_bytes()),
                                         ("doc_xlsx_blank", "blank.xlsx", None)):
            if content is None:
                buf = io.BytesIO()
                with pd.ExcelWriter(buf, engine="openpyxl") as w:
                    pd.DataFrame({"E": []}).to_excel(w, sheet_name="S", index=False)
                content = buf.getvalue()
            up = await c.post("/api/v1/documents/upload", files={"file": (filename, content)},
                              data={"space_id": "space1", "folder_path": "reports"})
            body = up.json()
            results[label + "_stored"] = [up.status_code, {k: v for k, v in body.items() if k in ("filename", "folder_path")}]
            r = await c.post("/api/v1/documents/load-spreadsheet", json={
                "file_id": body["file_id"], "filename": filename, "connection_name": f"conn {label}", "space_id": "space1"})
            results[label] = [r.status_code, r.json()]
        r = await c.post("/api/v1/documents/load-spreadsheet", json={
            "file_id": "0" * 8 + "-0000-0000-0000-" + "0" * 12, "filename": "a.csv", "connection_name": "c", "space_id": "space1"})
        results["doc_missing"] = [r.status_code, r.json()]
        r = await c.post("/api/v1/documents/load-spreadsheet", json={
            "file_id": "x", "filename": "a.pdf", "connection_name": "c", "space_id": "space1"})
        results["doc_bad_type"] = [r.status_code, r.json()]
    return results


def test_outcomes_are_unchanged(monkeypatch):
    _install(monkeypatch)
    before = _uploads_dir_listing()
    results = asyncio.run(_run_table())
    snapshot = {
        "responses": _norm(results),
        "registered": _norm([{k: v for k, v in d.items()} for d in _STATE["registered"]]),
        "connections": _norm([c.model_dump(mode="json", exclude={"created_at", "updated_at"})
                              for c in get_config().database_connections]),
        "databases": _db_contents(),
        "uploads_left_behind": sorted(set(_uploads_dir_listing()) - set(before)),
    }
    if os.environ.get("DUMP_SNAPSHOT"):
        print("SNAPSHOT=" + json.dumps(snapshot, sort_keys=True, default=str))
    assert json.loads(json.dumps(snapshot, sort_keys=True, default=str)) == EXPECTED


# ---------------------------------------------------------- loop not held ---

def _slow_load(*args, **kwargs):
    time.sleep(1)
    return {"table_name": "t", "row_count": 1, "column_count": 1}


async def _health_while(post):
    """Start `post`, and 0.2 s later (when its slow load is under way) ask /health.
    Returns how long after that moment /health was answered."""
    async with _client() as c:
        intended = time.monotonic() + 0.2

        async def health():
            await asyncio.sleep(0.2)
            r = await c.get("/health")
            assert r.status_code == 200
            return time.monotonic() - intended

        slow = asyncio.create_task(post(c))
        quick = asyncio.create_task(health())
        elapsed = await quick
        assert (await slow).status_code == 201
        return elapsed


def test_health_is_answered_during_a_slow_file_upload(monkeypatch):
    _install(monkeypatch, load_csv=_slow_load)

    async def post(c):
        return await c.post("/api/v1/upload-file", files={"file": ("a.csv", _csv_bytes())},
                            data={"name": "slow", "delimiter": ",", "has_header": "true", "selected_sheets": ""})

    elapsed = asyncio.run(_health_while(post))
    assert elapsed < 0.2, f"/health took {elapsed:.2f}s while a file was loading"


def test_health_is_answered_during_a_slow_document_load(monkeypatch):
    _install(monkeypatch, load_csv=_slow_load)

    async def go():
        async with _client() as c:
            up = await c.post("/api/v1/documents/upload", files={"file": ("o.csv", _csv_bytes())},
                              data={"space_id": "space1"})
            file_id = up.json()["file_id"]

        async def post(c):
            return await c.post("/api/v1/documents/load-spreadsheet", json={
                "file_id": file_id, "filename": "o.csv", "connection_name": "slow", "space_id": "space1"})

        return await _health_while(post)

    elapsed = asyncio.run(go())
    assert elapsed < 0.2, f"/health took {elapsed:.2f}s while a spreadsheet was loading"


def test_at_most_two_loads_run_at_once_and_health_stays_fast(monkeypatch):
    if not hasattr(rest_api, "_load_uploaded_file") and "_load_uploaded_file" not in open(rest_api.__file__).read():
        return  # the original loaded on the event loop: nothing to count
    import threading

    running = []
    peak = []
    lock = threading.Lock()

    def counting_load(*args, **kwargs):
        with lock:
            running.append(1)
            peak.append(len(running))
        time.sleep(0.5)
        with lock:
            running.pop()
        return {"table_name": "t", "row_count": 1, "column_count": 1}

    _install(monkeypatch, load_csv=counting_load)
    monkeypatch.delenv("SANDBOX_UPLOAD_LOAD_CONCURRENCY", raising=False)

    async def go():
        async with _client() as c:
            async def post(i):
                return await c.post("/api/v1/upload-file", files={"file": (f"a{i}.csv", _csv_bytes())},
                                    data={"name": f"gate{i}", "delimiter": ",", "has_header": "true", "selected_sheets": ""})

            tasks = [asyncio.create_task(post(i)) for i in range(5)]
            await asyncio.sleep(0.2)
            t0 = time.monotonic()
            health = await c.get("/health")
            elapsed = time.monotonic() - t0
            return [(await t).status_code for t in tasks], health.status_code, elapsed

    statuses, health, elapsed = asyncio.run(go())
    assert statuses == [201] * 5 and health == 200
    assert max(peak) == 2, f"{max(peak)} loads ran at once"
    assert elapsed < 0.2, f"/health took {elapsed:.2f}s"


def test_the_gate_size_comes_from_the_environment(monkeypatch):
    if not hasattr(rest_api, "_upload_load_slots"):
        return
    monkeypatch.setenv("SANDBOX_UPLOAD_LOAD_CONCURRENCY", "5")
    assert rest_api._upload_load_slots() == 5
    monkeypatch.setenv("SANDBOX_UPLOAD_LOAD_CONCURRENCY", "0")
    assert rest_api._upload_load_slots() == 1
    monkeypatch.setenv("SANDBOX_UPLOAD_LOAD_CONCURRENCY", "lots")
    assert rest_api._upload_load_slots() == 2


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
