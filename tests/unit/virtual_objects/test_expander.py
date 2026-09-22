from __future__ import annotations

from datetime import date

import pytest
import sqlglot
from sqlglot import exp

from sandbox.execution.virtual_objects.errors import VirtualObjectError
from sandbox.execution.virtual_objects.expander import expand

from .conftest import NOW, mssql_proc, objset, pg_fn, query_obj


def tables(sql: str, dialect: str) -> set[str]:
    return {t.name.lower() for t in sqlglot.parse_one(sql, read=dialect).find_all(exp.Table)}


# ------------------------------------------------------------ no-op guarantee


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT TOP 5 * FROM dbo.orders WITH (NOLOCK) ORDER BY id",
        "select  a,b -- comment\n from   customers",
        "SELECT sales_q_other FROM t",
        "SELECT * FROM my_sales_q",
    ],
)
def test_query_without_virtual_names_is_returned_byte_for_byte(tsql, sql):
    plan = expand(sql, tsql, objset(query_obj("sales_q", "SELECT 1 AS x")), now=NOW)
    assert plan.noop
    assert plan.sql == sql


def test_name_only_in_literal_or_column_is_untouched(tsql):
    objs = objset(query_obj("sales_q", "SELECT 1 AS x"))
    for sql in ("SELECT 'sales_q' AS label FROM orders", "SELECT sales_q FROM orders"):
        plan = expand(sql, tsql, objs, now=NOW)
        assert plan.noop and plan.sql == sql


def test_empty_set_never_parses(tsql):
    sql = "this is not SQL at all"
    assert expand(sql, tsql, objset(), now=NOW).sql == sql


# ------------------------------------------------------------ QUERY objects


@pytest.mark.parametrize(
    "ref",
    ["sales_q", "dbo.sales_q", "[dbo].[sales_q]", "SALES_Q", "[sales_q]", "erp.dbo.sales_q", "[dbo.sales_q]"],
)
def test_query_object_inlined_for_every_spelling(tsql, ref):
    objs = objset(query_obj("sales_q", "SELECT region, SUM(amount) AS total FROM dbo.sales GROUP BY region"))
    plan = expand(f"SELECT * FROM {ref}", tsql, objs, now=NOW)
    assert not plan.noop
    assert "sales_q" not in tables(plan.sql, "tsql")
    assert "sales" in tables(plan.sql, "tsql")
    assert [o.name for o in plan.used] == ["sales_q"]


def test_other_schema_is_not_the_virtual_object(tsql):
    objs = objset(query_obj("sales_q", "SELECT 1 AS x"))
    plan = expand("SELECT * FROM archive.sales_q", tsql, objs, now=NOW)
    assert plan.noop


def test_alias_preserved_and_hints_dropped(tsql):
    objs = objset(query_obj("sales_q", "SELECT id, cid FROM dbo.sales"))
    plan = expand(
        "SELECT s.id, c.name FROM sales_q AS s WITH (NOLOCK) JOIN customers c ON c.id = s.cid",
        tsql, objs, now=NOW,
    )
    assert "AS s" in plan.sql
    assert "NOLOCK" not in plan.sql
    assert "customers" in plan.sql


def test_unaliased_reference_keeps_name_as_alias(tsql):
    objs = objset(query_obj("sales_q", "SELECT id FROM dbo.sales"))
    plan = expand("SELECT sales_q.id FROM dbo.sales_q WHERE dbo.sales_q.id > 1", tsql, objs, now=NOW)
    assert "AS sales_q" in plan.sql
    assert "dbo.sales_q" not in plan.sql


def test_cte_with_same_name_shadows_object(tsql):
    objs = objset(query_obj("sales_q", "SELECT 1 AS x"))
    sql = "WITH sales_q AS (SELECT 2 AS x) SELECT x FROM sales_q"
    plan = expand(sql, tsql, objs, now=NOW)
    assert plan.noop


def test_object_inside_user_cte_subquery_and_union(tsql):
    objs = objset(query_obj("sales_q", "SELECT id FROM dbo.sales"))
    sql = (
        "WITH a AS (SELECT id FROM sales_q) "
        "SELECT id FROM a WHERE id IN (SELECT id FROM sales_q) "
        "UNION ALL SELECT id FROM sales_q"
    )
    plan = expand(sql, tsql, objs, now=NOW)
    assert "sales_q" not in tables(plan.sql, "tsql")


def test_definition_ctes_are_hoisted_and_renamed(tsql):
    objs = objset(query_obj("q", "WITH orders AS (SELECT id FROM dbo.raw_orders) SELECT id FROM orders"))
    plan = expand("SELECT q.id FROM q JOIN orders o ON o.id = q.id", tsql, objs, now=NOW)
    tree = sqlglot.parse_one(plan.sql, read="tsql")
    # T-SQL forbids WITH inside a derived table: it must sit at the top.
    assert tree.args.get("with_") is not None
    cte_names = [c.alias_or_name for c in tree.args["with_"].expressions]
    assert cte_names == ["mv1_orders"]
    # the caller's real `orders` table is still the real table
    joined = [t for t in tree.find_all(exp.Table) if t.alias == "o"]
    assert joined and joined[0].name == "orders"


def test_nested_query_objects(tsql):
    objs = objset(
        query_obj("base_q", "SELECT id, amount FROM dbo.sales"),
        query_obj("top_q", "SELECT id FROM base_q WHERE amount > 10"),
    )
    plan = expand("SELECT * FROM top_q", tsql, objs, now=NOW)
    assert tables(plan.sql, "tsql") == {"sales"}
    assert {o.name for o in plan.used} == {"base_q", "top_q"}


def test_cycle_is_rejected(tsql):
    objs = objset(query_obj("a", "SELECT x FROM b"), query_obj("b", "SELECT x FROM a"))
    with pytest.raises(VirtualObjectError, match="cycle"):
        expand("SELECT * FROM a", tsql, objs, now=NOW)


def test_unparsable_query_referencing_object_raises(tsql):
    with pytest.raises(VirtualObjectError):
        expand("SELECT * FROM sales_q WHERE (", tsql, objset(query_obj("sales_q", "SELECT 1 AS x")), now=NOW)


def test_row_filter_shape_from_permission_guard(tsql):
    # The data-analyst guard injects WHERE <alias>.<col> = '...' on the
    # object's name; that must keep working after expansion.
    objs = objset(query_obj("sales_q", "SELECT region FROM dbo.sales"))
    plan = expand("SELECT * FROM sales_q WHERE sales_q.region = 'EU'", tsql, objs, now=NOW)
    assert "sales_q.region = 'EU'" in plan.sql


def test_postgres_and_mysql_dialects(pg, mysql):
    objs = objset(query_obj("sales_q", "SELECT id FROM sales"))
    p = expand('SELECT * FROM public."sales_q" s', pg, objs, now=NOW)
    assert "sales_q" not in tables(p.sql, "postgres")
    m = expand("SELECT * FROM erp.sales_q s LIMIT 5", mysql, objs, now=NOW)
    assert "sales_q" not in tables(m.sql, "mysql")
    assert "LIMIT 5" in m.sql


def test_parameters_placeholders_survive(pg):
    objs = objset(query_obj("sales_q", "SELECT id FROM sales"))
    plan = expand("SELECT * FROM sales_q WHERE id = :id", pg, objs, now=NOW)
    assert ":id" in plan.sql


# ------------------------------------------------------------ SQL Server procedures


def test_mssql_procedure_becomes_temp_table_step(tsql):
    proc = mssql_proc("sales_ytd")
    plan = expand(
        "SELECT s.region, SUM(s.amount) FROM sales_ytd s JOIN regions r ON r.code = s.region GROUP BY s.region",
        tsql, objset(proc), now=NOW,
    )
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.temp_name.startswith("#mv_abcdef12_")
    assert step.temp_name in plan.sql
    assert "rpt_Sales" not in plan.sql
    assert step.params == [("Start", date(2026, 1, 1)), ("End", date(2026, 5, 17))]


def test_same_procedure_twice_materialized_once(tsql):
    proc = mssql_proc("sales_ytd")
    plan = expand("SELECT * FROM sales_ytd a JOIN sales_ytd b ON a.region = b.region", tsql, objset(proc), now=NOW)
    assert len(plan.steps) == 1
    assert plan.sql.count(plan.steps[0].temp_name) == 2


def test_procedure_nested_in_query_object(tsql):
    objs = objset(mssql_proc("sales_ytd"), query_obj("eu_sales", "SELECT * FROM sales_ytd WHERE region = 'EU'"))
    plan = expand("SELECT * FROM eu_sales", tsql, objs, now=NOW)
    assert len(plan.steps) == 1
    assert plan.steps[0].temp_name in plan.sql


def test_procedure_on_wrong_dialect_rejected(pg):
    with pytest.raises(VirtualObjectError):
        expand("SELECT * FROM sales_ytd", pg, objset(mssql_proc("sales_ytd")), now=NOW)


# ------------------------------------------------------------ Postgres functions


def test_pg_function_inlined_with_typed_literals(pg):
    plan = expand("SELECT * FROM monthly f WHERE f.x > 1", pg, objset(pg_fn("monthly")), now=NOW)
    assert "public.fn_sales(CAST('2026-05-01' AS DATE)) AS f" in plan.sql
    assert not plan.steps


def test_pg_function_argument_escaping(pg):
    from sandbox.execution.virtual_objects.models import ParamSpec

    fn = pg_fn("by_name", params=[ParamSpec("p_name", "text", "O'Brien'); DROP TABLE x; --")])
    plan = expand("SELECT * FROM by_name", pg, objset(fn), now=NOW)
    # One statement, the value is a single escaped literal.
    assert len(sqlglot.parse(plan.sql, read="postgres")) == 1
    assert "'O''Brien''); DROP TABLE x; --'" in plan.sql


def test_pg_function_named_notation_when_omitting(pg):
    from sandbox.execution.virtual_objects.models import ParamSpec

    fn = pg_fn("f", routine_name="FnMixed", params=[ParamSpec("a", "int", "1"), ParamSpec("b", "int", None, omit=True)])
    plan = expand("SELECT * FROM f", pg, objset(fn), now=NOW)
    assert 'public."FnMixed"(a => CAST(\'1\' AS INT))' in plan.sql
