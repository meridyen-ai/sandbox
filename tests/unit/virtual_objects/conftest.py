from __future__ import annotations

from datetime import datetime

import pytest

from sandbox.execution.virtual_objects.expander import DialectContext
from sandbox.execution.virtual_objects.models import (
    ParamSpec,
    VirtualColumn,
    VirtualObject,
)
from sandbox.execution.virtual_objects.registry import VirtualObjectSet

NOW = datetime(2026, 5, 17, 14, 30, 0)


def query_obj(name: str, sql: str, **kw) -> VirtualObject:
    return VirtualObject(
        id=kw.pop("id", f"q-{name}"),
        connection_id="c1",
        kind="QUERY",
        name=name,
        sql_text=sql,
        normalized_sql=sql,
        columns=[VirtualColumn("x", "int")],
        **kw,
    )


def mssql_proc(name: str, **kw) -> VirtualObject:
    return VirtualObject(
        id=kw.pop("id", "abcdef1234567890"),
        connection_id="c1",
        kind="PROCEDURE",
        name=name,
        routine_type="mssql_procedure",
        routine_schema=kw.pop("routine_schema", "dbo"),
        routine_name=kw.pop("routine_name", "rpt_Sales"),
        params=kw.pop("params", [ParamSpec("Start", "date", "{{start_of_year}}"), ParamSpec("End", "date", "{{today}}")]),
        columns=kw.pop("columns", [VirtualColumn("region", "nvarchar(50)"), VirtualColumn("amount", "decimal(18,2)")]),
        **kw,
    )


def pg_fn(name: str, **kw) -> VirtualObject:
    return VirtualObject(
        id=kw.pop("id", "fn1"),
        connection_id="c1",
        kind="PROCEDURE",
        name=name,
        routine_type="pg_function",
        routine_schema=kw.pop("routine_schema", "public"),
        routine_name=kw.pop("routine_name", "fn_sales"),
        params=kw.pop("params", [ParamSpec("p_from", "date", "{{start_of_month}}")]),
        columns=[VirtualColumn("x", "integer")],
        **kw,
    )


def objset(*objs: VirtualObject) -> VirtualObjectSet:
    return VirtualObjectSet({o.key: o for o in objs})


@pytest.fixture
def tsql() -> DialectContext:
    return DialectContext(db_type="mssql", schema="dbo", database="erp")


@pytest.fixture
def pg() -> DialectContext:
    return DialectContext(db_type="postgresql", schema="public", database="erp")


@pytest.fixture
def mysql() -> DialectContext:
    return DialectContext(db_type="mysql", schema="erp", database="erp")
