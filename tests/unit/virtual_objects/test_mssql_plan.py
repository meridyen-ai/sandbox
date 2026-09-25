from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import SecretStr

from sandbox.connectors.mssql import MSSQLConnector, _literal, _temp_table_ddl
from sandbox.core.config import DatabaseConnectionConfig, DatabaseType
from sandbox.core.exceptions import SQLExecutionError
from sandbox.execution.virtual_objects.expander import expand
from sandbox.execution.virtual_objects.models import VirtualColumn

from .conftest import NOW, mssql_proc, objset


class FakeCursor:
    def __init__(self, fail_on: dict[str, Exception] | None = None, proc_sets=None):
        self.executed: list[str] = []
        self.fail_on = fail_on or {}
        self.proc_sets = proc_sets or [[("EU", Decimal("1.5"))]]
        self.description = None
        self._sets: list = []
        self.rowcount = -1

    def execute(self, sql, args=None):
        self.executed.append(sql)
        for needle, exc in self.fail_on.items():
            if needle in sql:
                self.fail_on.pop(needle)
                raise exc
        if sql.startswith("EXEC"):
            self._sets = [list(rows) for rows in self.proc_sets]
            self._next()
        elif sql.startswith("SELECT"):
            self._sets = [[("EU", Decimal("1.5"))]]
            self._next()
        else:
            self._sets, self.description = [], None

    def _next(self):
        if not self._sets:
            self.description = None
            return False
        self._rows = self._sets.pop(0)
        self.description = [("region", 1), ("amount", 3)]
        return True

    def nextset(self):
        return self._next() or None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def fetchmany(self, n):
        rows, self._rows = self._rows[:n], self._rows[n:]
        return rows


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def connector() -> MSSQLConnector:
    return MSSQLConnector(DatabaseConnectionConfig(
        id="c1", name="c", db_type=DatabaseType.MSSQL, host="h", port=1433,
        database="erp", username="u", password=SecretStr("p"),
    ))


def plan_for(tsql, **kw):
    return expand("SELECT region, SUM(amount) FROM sales_ytd GROUP BY region", tsql, objset(mssql_proc("sales_ytd", **kw)), now=NOW)


async def test_insert_exec_sequence_and_cleanup(tsql):
    plan = plan_for(tsql)
    temp = plan.steps[0].temp_name
    cur = FakeCursor()
    result = await connector().execute_plan(FakeConn(cur), plan)
    assert result.rows == [("EU", Decimal("1.5"))]
    assert cur.executed[0] == f"IF OBJECT_ID('tempdb..{temp}') IS NOT NULL DROP TABLE {temp}"
    assert cur.executed[1].startswith(f"CREATE TABLE {temp} ([region] nvarchar(50) COLLATE DATABASE_DEFAULT NULL")
    assert cur.executed[2] == (
        f"INSERT INTO {temp} EXEC [dbo].[rpt_Sales] @Start = '20260101', @End = '20260517'"
    )
    assert cur.executed[3] == plan.sql
    assert cur.executed[-1].endswith(f"DROP TABLE {temp}")


async def test_cleanup_runs_when_query_fails(tsql):
    plan = plan_for(tsql)
    temp = plan.steps[0].temp_name
    cur = FakeCursor(fail_on={"SUM(amount)": RuntimeError("boom")})
    with pytest.raises(SQLExecutionError):
        await connector().execute_plan(FakeConn(cur), plan)
    assert cur.executed[-1].endswith(f"DROP TABLE {temp}")


async def test_nested_insert_exec_falls_back_to_client_mode(tsql):
    plan = plan_for(tsql)
    temp = plan.steps[0].temp_name
    cur = FakeCursor(fail_on={"INSERT INTO": RuntimeError(8164, b"An INSERT EXEC statement cannot be nested.")})
    await connector().execute_plan(FakeConn(cur), plan)
    assert f"DELETE FROM {temp}" in cur.executed
    assert any(s.startswith("EXEC [dbo].[rpt_Sales]") for s in cur.executed)
    assert f"INSERT INTO {temp} VALUES (N'EU',1.5)" in cur.executed
    assert plan.steps[0].fetched_rows == [("EU", Decimal("1.5"))]


async def test_client_mode_picks_result_set(tsql):
    plan = plan_for(tsql, result_set_index=1, materialization="client")
    plan.steps[0].mode = "client"
    cur = FakeCursor(proc_sets=[[("ignored", Decimal(0))], [("EU", Decimal("2")), ("US", Decimal("3"))]])
    await connector().execute_plan(FakeConn(cur), plan)
    assert plan.steps[0].fetched_rows == [("EU", Decimal("2")), ("US", Decimal("3"))]


async def test_missing_result_set_is_reported(tsql):
    plan = plan_for(tsql, result_set_index=3, materialization="client")
    cur = FakeCursor()
    with pytest.raises(SQLExecutionError, match="result set #4"):
        await connector().execute_plan(FakeConn(cur), plan)


async def test_cached_rows_are_inserted_without_exec(tsql):
    plan = plan_for(tsql)
    plan.steps[0].cached_rows = [("EU", Decimal("9"))]
    cur = FakeCursor()
    await connector().execute_plan(FakeConn(cur), plan)
    assert not any(s.startswith("EXEC") or " EXEC " in s for s in cur.executed)


def test_literals():
    assert _literal(None) == "NULL"
    assert _literal("O'Brien") == "N'O''Brien'"
    assert _literal(b"\x01\xff") == "0x01ff"
    assert _literal(True) == "1"
    assert _literal(Decimal("1.50")) == "1.50"
    assert _literal(float("nan")) == "NULL"
    assert _literal(date(2026, 1, 2)) == "'20260102'"
    assert _literal(datetime(2026, 1, 2, 3, 4, 5, 123456), "datetime") == "'2026-01-02T03:04:05.123'"
    assert _literal(datetime(2026, 1, 2, 3, 4, 5, 123456), "datetime2(7)") == "'2026-01-02T03:04:05.1234560'"


def test_temp_table_ddl_rejects_injected_types():
    from sandbox.execution.virtual_objects.errors import VirtualObjectError

    assert _temp_table_ddl([VirtualColumn("v", "rowversion")]) == "[v] binary(8) NULL"
    with pytest.raises(VirtualObjectError):
        _temp_table_ddl([VirtualColumn("x", "int) ; DROP TABLE t --")])
