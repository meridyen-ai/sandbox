"""Oracle connector: connect arguments, read-only execution, values, catalog.

The driver is replaced by a fake: nothing here opens a socket. The same paths
run against a real Oracle Free database in the manual end-to-end check.
"""

from __future__ import annotations

import sys
import types

import pytest
from pydantic import SecretStr

from sandbox.connectors import factory
from sandbox.connectors import oracle as oracle_module
from sandbox.connectors.oracle import OracleConnector, connect_params, oracle_identifier
from sandbox.core.config import DatabaseConnectionConfig, DatabaseType
from sandbox.core.exceptions import ConnectionError, SQLExecutionError


def _cfg(**kw) -> DatabaseConnectionConfig:
    base = dict(
        id="ora-1", name="ora", db_type=DatabaseType.ORACLE, host="db.example.com",
        port=1521, database="FREEPDB1", username="docs", password=SecretStr("pw"),
        query_timeout=120, connection_timeout=7,
    )
    base.update(kw)
    return DatabaseConnectionConfig(**base)


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self.rowcount = 0
        self.arraysize = 100
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None, **kw):
        self.conn.log.append((sql, params, kw))
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError("ORA-00942: table or view does not exist")
        if sql.startswith("SELECT"):
            self.description = [("DOC_KEY", types.SimpleNamespace(name="DB_TYPE_VARCHAR")),
                                ("BODY", types.SimpleNamespace(name="DB_TYPE_CLOB"))]
            self._rows = [("P-1", "İş güvenliği şartları")]

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class FakeConn:
    def __init__(self, fail_on=None):
        self.log = []
        self.rollbacks = 0
        self.call_timeout = 0
        self.fail_on = fail_on

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass

    def ping(self):
        pass


@pytest.fixture
def fake_driver(monkeypatch):
    calls = {}
    conn = FakeConn()

    class Error(Exception):
        pass

    def connect(**kw):
        calls.update(kw)
        return conn

    monkeypatch.setitem(sys.modules, "oracledb", types.SimpleNamespace(connect=connect, Error=Error))

    from sandbox.connectors.host_policy import VettedHost

    async def vetted(cfg):
        return VettedHost(addresses=("203.0.113.9",))

    monkeypatch.setattr(oracle_module, "vet_destination", vetted)
    return calls, conn


def test_oracle_is_a_connector_type():
    assert factory.has_connector("oracle")
    assert factory.get_connector("oracle", _cfg()).__class__ is OracleConnector


def test_identifier_folding():
    assert oracle_identifier("docs") == "DOCS"
    assert oracle_identifier('"MixedCase"') == "MixedCase"
    assert oracle_identifier("weird name") == "weird name"


def test_connect_params_service_name_and_sid():
    p = connect_params(_cfg(), host="h", ssl_mode="disable", ssl_context=None)
    assert p["service_name"] == "FREEPDB1" and "sid" not in p
    assert p["port"] == 1521 and p["tcp_connect_timeout"] == 7.0
    assert "protocol" not in p
    p = connect_params(_cfg(extra_params={"sid": "ORCL"}), host="h", ssl_mode="disable", ssl_context=None)
    assert p["sid"] == "ORCL" and "service_name" not in p


@pytest.mark.parametrize("mode,dn_match", [("require", False), ("verify-ca", False), ("verify-full", True)])
def test_connect_params_tls(mode, dn_match):
    ctx = object()
    p = connect_params(_cfg(), host="h", ssl_mode=mode, ssl_context=ctx)
    assert p["protocol"] == "tcps" and p["ssl_context"] is ctx
    assert p["ssl_server_dn_match"] is dn_match


@pytest.mark.asyncio
async def test_connect_dials_checked_address_and_sets_timeout_and_schema(fake_driver):
    calls, conn = fake_driver
    c = OracleConnector(_cfg(schema_name="docs_store"))
    got = await c.connect()
    assert got is conn
    assert calls["host"] == "203.0.113.9"  # the vetted address, not the name
    assert conn.call_timeout == 120_000
    assert conn.log[0][0] == 'ALTER SESSION SET CURRENT_SCHEMA = "DOCS_STORE"'


@pytest.mark.asyncio
async def test_verify_full_dials_the_name(fake_driver, monkeypatch):
    calls, _ = fake_driver
    monkeypatch.setattr(oracle_module, "build_ssl_context", lambda *a, **k: "ctx")
    await OracleConnector(_cfg(ssl_mode="verify-full")).connect()
    assert calls["host"] == "db.example.com" and calls["protocol"] == "tcps"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["allow", "prefer"])
async def test_opportunistic_tls_is_refused(fake_driver, mode):
    with pytest.raises(ConnectionError):
        await OracleConnector(_cfg(ssl_mode=mode)).connect()


@pytest.mark.asyncio
async def test_read_only_transaction_and_lobs_as_values():
    conn = FakeConn()
    result = await OracleConnector(_cfg()).execute_read_only(conn, "SELECT doc_key, body FROM docs;")
    sqls = [entry[0] for entry in conn.log]
    assert sqls == ["SET TRANSACTION READ ONLY", "SELECT doc_key, body FROM docs"]
    assert conn.log[1][2] == {"fetch_lobs": False}
    assert conn.rollbacks == 2  # before (opens the transaction) and after
    assert result.columns == ["DOC_KEY", "BODY"]
    assert result.column_types == ["VARCHAR", "CLOB"]
    assert result.rows == [("P-1", "İş güvenliği şartları")]


@pytest.mark.asyncio
async def test_parameters_are_bound_by_name_and_unused_ones_dropped():
    conn = FakeConn()
    await OracleConnector(_cfg()).execute(conn, "SELECT * FROM docs WHERE k = :k", {"k": "A", "x": 1})
    assert conn.log[0][1] == {"k": "A"}


@pytest.mark.asyncio
async def test_errors_are_sql_execution_errors_and_still_roll_back():
    conn = FakeConn(fail_on="FROM missing")
    with pytest.raises(SQLExecutionError):
        await OracleConnector(_cfg()).execute_read_only(conn, "SELECT * FROM missing")
    assert conn.rollbacks == 2


@pytest.mark.asyncio
async def test_catalog_is_scoped_to_the_schema():
    conn = FakeConn()
    c = OracleConnector(_cfg(schema_name="docs"))
    await c.get_table_entries(conn)
    sql, params, _ = conn.log[-1]
    assert "OWNER = :owner" in sql and params == {"owner": "DOCS"}
    await OracleConnector(_cfg()).get_table_entries(conn)
    assert "SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA')" in conn.log[-1][0]
