from __future__ import annotations

from datetime import date, datetime

import pytest

from sandbox.execution.virtual_objects.errors import VirtualObjectError, sanitize
from sandbox.execution.virtual_objects.expander import expand
from sandbox.execution.virtual_objects.models import ParamSpec
from sandbox.execution.virtual_objects.tokens import convert_value, resolve_params, resolve_token
from sandbox.execution.virtual_objects.validation import (
    normalize_query_definition,
    unique_column_names,
    validate_name,
    validate_sql_type,
)
from sandbox.services.schema_sql import build_sample_query, merge_virtual_entries, virtual_columns

from .conftest import NOW, mssql_proc, objset, query_obj

# ------------------------------------------------------------ names


@pytest.mark.parametrize("name", ["sales_ytd", "SalesQ", "_x1"])
def test_valid_names(tsql, name):
    validate_name(name, tsql)


@pytest.mark.parametrize("name", ["resp_times", "my exec", "1abc", "a-b", "x;y", "exec", "select", ""])
def test_rejected_names(tsql, name):
    # resp_times contains the banned "sp_" substring: every query using it
    # would be rejected by the SQL validator, so it is refused up front.
    with pytest.raises(VirtualObjectError):
        validate_name(name, tsql)


# ------------------------------------------------------------ definitions


def test_definition_comments_stripped_and_validated(tsql):
    sql = "-- monthly totals\nSELECT region, /* sum */ SUM(amount) AS total FROM dbo.sales GROUP BY region;"
    out = normalize_query_definition(sql, tsql)
    assert "--" not in out and "/*" not in out
    assert out.startswith("SELECT")


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM sales",
        "SELECT 1 AS a; SELECT 2 AS b",
        "SELECT * INTO #t FROM sales",
        "SELECT * FROM sales WHERE id = @id",
        "UPDATE sales SET x = 1",
        "SELECT * FROM information_schema.tables",
        "SELECT region FROM dbo.sales ORDER BY region",
    ],
)
def test_bad_definitions(tsql, sql):
    with pytest.raises(VirtualObjectError):
        normalize_query_definition(sql, tsql)


def test_order_by_with_top_is_allowed_on_tsql(tsql):
    normalize_query_definition("SELECT TOP 10 region FROM dbo.sales ORDER BY region", tsql)


def test_order_by_allowed_on_postgres(pg):
    normalize_query_definition("SELECT region FROM sales ORDER BY region", pg)


def test_sql_types():
    for ok in ("nvarchar(max)", "decimal(18, 2)", "int", "datetime2(7)", "double precision", "text[]"):
        validate_sql_type(ok, "x")
    for bad in ("int); DROP TABLE x --", "varchar(10) COLLATE x", "a'b"):
        with pytest.raises(VirtualObjectError):
            validate_sql_type(bad, "x")


def test_unique_column_names():
    assert unique_column_names(["a", "", "a", None, "A"]) == ["a", "column_2", "a_2", "column_4", "A_3"]


# ------------------------------------------------------------ tokens


@pytest.mark.parametrize(
    "token,expected",
    [
        ("{{today}}", date(2026, 5, 17)),
        ("{{yesterday}}", date(2026, 5, 16)),
        ("{{start_of_week}}", date(2026, 5, 11)),
        ("{{start_of_month}}", date(2026, 5, 1)),
        ("{{end_of_month}}", date(2026, 5, 31)),
        ("{{start_of_prev_month}}", date(2026, 4, 1)),
        ("{{end_of_prev_month}}", date(2026, 4, 30)),
        ("{{start_of_quarter}}", date(2026, 4, 1)),
        ("{{start_of_year}}", date(2026, 1, 1)),
        ("{{end_of_year}}", date(2026, 12, 31)),
        ("{{start_of_prev_year}}", date(2025, 1, 1)),
        ("{{ today - 7d }}", date(2026, 5, 10)),
        ("{{today+2w}}", date(2026, 5, 31)),
        ("{{start_of_month-1m}}", date(2026, 4, 1)),
        ("{{end_of_month+9m}}", date(2027, 2, 28)),
        ("{{start_of_year-1y}}", date(2025, 1, 1)),
    ],
)
def test_tokens(token, expected):
    assert resolve_token(token, NOW) == expected


def test_convert_by_type():
    assert convert_value("{{today}}", "datetime", NOW) == datetime(2026, 5, 17)
    assert convert_value("{{now}}", "datetime2", NOW) == NOW
    assert convert_value("2024-02-03", "date", NOW) == date(2024, 2, 3)
    assert convert_value("42", "int", NOW) == 42
    assert str(convert_value("1.50", "decimal(18,2)", NOW)) == "1.50"
    assert convert_value("true", "bit", NOW) is True
    assert convert_value(None, "int", NOW) is None
    assert convert_value("", "int", NOW) is None
    assert convert_value("x", "nvarchar(10)", NOW) == "x"
    with pytest.raises(VirtualObjectError):
        convert_value("abc", "int", NOW)
    with pytest.raises(VirtualObjectError):
        convert_value("{{tomorrowish}}", "date", NOW)


def test_omitted_params_are_skipped():
    specs = [ParamSpec("a", "int", "1"), ParamSpec("b", "int", "2", omit=True)]
    assert [(p.name, p.value) for p in resolve_params(specs, NOW)] == [("a", 1)]


# ------------------------------------------------------------ sanitize


def test_sanitize_hides_procedure_and_temp_table(tsql):
    proc = mssql_proc("sales_ytd")
    plan = expand("SELECT * FROM sales_ytd", tsql, objset(proc), now=NOW)
    temp = plan.steps[0].temp_name
    msg = (
        f"(8164, 'An INSERT EXEC statement cannot be nested. Procedure [dbo].[rpt_Sales] line 3; "
        f"Invalid column name in {temp}; see dbo.rpt_Sales')"
    )
    out = sanitize(msg, plan)
    assert "rpt_Sales" not in out
    assert temp not in out
    assert "INSERT EXEC" not in out
    assert "sales_ytd" in out


def test_sanitize_noop_plan_leaves_message():
    assert sanitize("boom", None) == "boom"


# ------------------------------------------------------------ schema helpers


def test_sample_queries_per_dialect():
    assert build_sample_query("mssql", "dbo", "Order]s", ["a"], 5) == "SELECT TOP 5 [a] FROM [dbo].[Order]]s]"
    assert build_sample_query("postgresql", None, "t", None, 3) == 'SELECT * FROM "t" LIMIT 3'
    assert build_sample_query("mysql", "erp", "t", ["c"], 3) == "SELECT `c` FROM `erp`.`t` LIMIT 3"


def test_merge_virtual_entries_virtual_wins():
    q = query_obj("orders", "SELECT 1 AS x")
    p = mssql_proc("sales_ytd")
    entries = [{"name": "Orders", "type": "TABLE"}, {"name": "customers", "type": "VIEW"}]
    merged, conflicts = merge_virtual_entries(entries, objset(q, p))
    assert merged == [
        {"name": "customers", "type": "VIEW"},
        {"name": "orders", "type": "QUERY"},
        {"name": "sales_ytd", "type": "PROCEDURE"},
    ]
    assert [c.name for c in conflicts] == ["orders"]
    cols = virtual_columns(objset(p))
    assert [c["name"] for c in cols["sales_ytd"]] == ["region", "amount"]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(amount) FROM dbo.sales",
        "SELECT a, b AS a FROM t",
        "SELECT 1 AS x UNION ALL SELECT 2",
        "SELECT COUNT(*), region FROM t GROUP BY region",
    ],
)
def test_unnamed_or_duplicate_columns_rejected(tsql, sql):
    if sql.startswith("SELECT 1 AS x UNION"):
        normalize_query_definition(sql, tsql)  # names come from the first branch
        return
    with pytest.raises(VirtualObjectError):
        normalize_query_definition(sql, tsql)


def test_star_and_qualified_star_allowed(tsql):
    normalize_query_definition("SELECT s.*, c.name AS customer FROM dbo.sales s JOIN dbo.c c ON c.id = s.cid", tsql)


def test_year_tokens():
    assert resolve_token("{{year}}", NOW) == 2026
    assert resolve_token("{{year-1y}}", NOW) == 2025
    assert resolve_token("{{last_3_years}}", NOW) == "2024,2025,2026"
    assert resolve_token("{{last_5_years}}", NOW) == "2022,2023,2024,2025,2026"
    assert convert_value("{{last_3_years}}", "nvarchar(max)", NOW) == "2024,2025,2026"
    assert convert_value("{{year}}", "int", NOW) == 2026
    with pytest.raises(VirtualObjectError):
        resolve_token("{{year-1d}}", NOW)
    with pytest.raises(VirtualObjectError):
        convert_value("{{last_3_years}}", "date", NOW)
