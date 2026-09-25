"""
Save-time validation of virtual object names and definitions.

A definition is held to the same rules as a query a caller sends to
``/execute/sql`` — it runs with the connection's credentials on every query
that references it, so it must not be a way around the SQL validator.
"""

from __future__ import annotations

import re

from sqlglot import exp

from sandbox.execution.virtual_objects.errors import VirtualObjectError
from sandbox.execution.virtual_objects.expander import DialectContext, parse_single, render

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
# Database types are copied into generated SQL (temp-table DDL, CASTs), so they
# are held to a strict shape: word(s), optional (n[,m]) or (max), optional [].
SQL_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_ ]{0,63}(\(\s*(max|\d{1,4})(\s*,\s*\d{1,4})?\s*\))?(\[\])?$", re.IGNORECASE)
ROUTINE_NAME_RE = re.compile(r"^[^\x00-\x1f\[\]\"`;]{1,128}$")


def _validator():
    from sandbox.execution.sql_executor import SQLValidator

    return SQLValidator()


def validate_name(name: str, ctx: DialectContext) -> None:
    if not NAME_RE.match(name or ""):
        raise VirtualObjectError(
            "Name must start with a letter or underscore and contain only letters, "
            "digits and underscores (max 100 characters)",
            field="name",
        )
    probe = f"SELECT * FROM {name}"
    errors = _validator().validate(probe)
    if errors:
        raise VirtualObjectError(
            f"'{name}' cannot be used as a name: it contains a reserved pattern", field="name"
        )
    try:
        tree = parse_single(probe, ctx.dialect)
    except VirtualObjectError:
        raise VirtualObjectError(f"'{name}' is a reserved word in this database", field="name")
    table = tree.find(exp.Table)
    if table is None or not isinstance(table.this, exp.Identifier) or table.name != name:
        raise VirtualObjectError(f"'{name}' is a reserved word in this database", field="name")


def validate_sql_type(sql_type: str, what: str) -> None:
    if sql_type and not SQL_TYPE_RE.match(sql_type.strip()):
        raise VirtualObjectError(f"Unsupported type '{sql_type}' for {what}")


def validate_routine_name(value: str | None, what: str) -> None:
    if not value or not ROUTINE_NAME_RE.match(value):
        raise VirtualObjectError(f"Invalid {what}")


def normalize_query_definition(sql_text: str, ctx: DialectContext) -> str:
    """Parse, check and canonicalize a custom query definition.

    Returns the SQL that gets inlined: comments stripped (the validator bans
    ``--`` and ``/*``), one SELECT / set operation, no variables, no INTO, no
    locking, and passing the same validator as caller queries.
    """
    text = (sql_text or "").strip().rstrip(";").strip()
    if not text:
        raise VirtualObjectError("SQL is required", field="sql_text")

    tree = parse_single(text, ctx.dialect)
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        raise VirtualObjectError("A custom query must be a single SELECT statement", field="sql_text")

    for node in tree.walk():
        if isinstance(node, exp.Into):
            raise VirtualObjectError("SELECT … INTO is not allowed", field="sql_text")
        if isinstance(node, exp.Lock):
            raise VirtualObjectError("Locking clauses (FOR UPDATE …) are not allowed", field="sql_text")
        if isinstance(node, exp.Command):
            raise VirtualObjectError("Only plain SELECT syntax is supported", field="sql_text")
        if isinstance(node, (exp.Parameter, exp.Placeholder, exp.SessionParameter)):
            raise VirtualObjectError(
                "Variables and parameters are not supported in a custom query; "
                "use a stored procedure for parameterized logic",
                field="sql_text",
            )

    if ctx.db_type == "mssql" and tree.args.get("order") is not None:
        if tree.args.get("limit") is None and tree.args.get("offset") is None:
            raise VirtualObjectError(
                "SQL Server does not allow ORDER BY in a custom query without TOP or OFFSET; "
                "remove the ORDER BY (callers sort their own results)",
                field="sql_text",
            )

    _check_projection_names(tree)

    normalized = render(tree, ctx.dialect)
    errors = _validator().validate(normalized)
    if errors:
        raise VirtualObjectError("; ".join(errors), field="sql_text")
    return normalized


def _check_projection_names(tree: exp.Expression) -> None:
    """Every output column needs a name — it becomes a column of the table.

    Checked on the SQL rather than the described result: once the definition
    is wrapped as a derived table, sqlglot would silently name an unaliased
    expression ``_col_0``.
    """
    select = tree
    while isinstance(select, exp.SetOperation):
        select = select.this  # a UNION takes its column names from the first branch
    if not isinstance(select, exp.Select):
        return
    names: list[str] = []
    for projection in select.expressions:
        if isinstance(projection, exp.Star) or (
            isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)
        ):
            continue
        name = projection.alias_or_name if isinstance(projection, (exp.Alias, exp.Column)) else ""
        if not name:
            raise VirtualObjectError(
                f"Every column needs a name; add an alias to '{projection.sql()[:60]}' "
                "(e.g. SUM(amount) AS total_amount)",
                field="sql_text",
            )
        names.append(name.lower())
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise VirtualObjectError(
            f"Column names must be unique; alias the duplicates: {', '.join(dupes)}",
            field="sql_text",
        )


def unique_column_names(names: list[str | None]) -> list[str]:
    """Blank → ``column_<n>``; duplicates → ``name_2``, ``name_3`` …"""
    out: list[str] = []
    seen: set[str] = set()
    for i, raw in enumerate(names, start=1):
        base = (raw or "").strip() or f"column_{i}"
        name = base
        n = 2
        while name.lower() in seen:
            name = f"{base}_{n}"
            n += 1
        seen.add(name.lower())
        out.append(name)
    return out
