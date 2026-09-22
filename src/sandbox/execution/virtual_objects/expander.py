"""
Rewrite SQL that references virtual objects into SQL the database can run.

The caller wrote ``SELECT … FROM sales_ytd s JOIN customers c …`` as if
``sales_ytd`` were a table. Depending on what backs it, each reference becomes:

* QUERY            → ``(<definition>) AS s`` — a derived table. Any CTEs in the
                     definition are hoisted into the statement's own WITH,
                     because T-SQL forbids WITH inside a derived table.
* pg_function      → ``schema.fn(CAST('…' AS type), …) AS s``.
* mssql_procedure  → ``#mv_<id>_<n> AS s``, plus a ``MaterializeStep`` telling
                     the connector to fill that session temp table from the
                     procedure before running the query.

Queries that mention no virtual object name are returned untouched, without
being parsed — the rewrite can never change SQL that does not need it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from sandbox.execution.virtual_objects.errors import VirtualObjectError
from sandbox.execution.virtual_objects.models import (
    KIND_PROCEDURE,
    KIND_QUERY,
    ROUTINE_MSSQL_PROCEDURE,
    ROUTINE_PG_FUNCTION,
    ExpansionPlan,
    MaterializeStep,
    VirtualObject,
)
from sandbox.execution.virtual_objects.registry import VirtualObjectSet
from sandbox.execution.virtual_objects.tokens import now_in, resolve_params, resolve_timezone

MAX_DEPTH = 4

# sandbox db_type → sqlglot dialect. None = sqlglot's generic dialect (HANA).
DIALECTS: dict[str, str | None] = {
    "mssql": "tsql",
    "postgresql": "postgres",
    "mysql": "mysql",
    "saphana": None,
}


@dataclass(frozen=True)
class DialectContext:
    db_type: str
    schema: str
    database: str
    tz: ZoneInfo = ZoneInfo("UTC")

    @property
    def dialect(self) -> str | None:
        return DIALECTS.get(self.db_type)


def context_for(conn_cfg: Any) -> DialectContext:
    """Expansion context of a ``DatabaseConnectionConfig``."""
    db_type = getattr(conn_cfg.db_type, "value", conn_cfg.db_type)
    return DialectContext(
        db_type=db_type,
        schema=effective_schema(conn_cfg),
        database=conn_cfg.database or "",
        tz=resolve_timezone(conn_cfg.extra_params),
    )


def effective_schema(conn_cfg: Any) -> str:
    """The schema a connection's catalog lists (and virtual objects live in)."""
    db_type = getattr(conn_cfg.db_type, "value", conn_cfg.db_type)
    if conn_cfg.schema_name:
        return conn_cfg.schema_name
    if db_type == "mssql":
        return "dbo"
    if db_type == "postgresql":
        return "public"
    if db_type == "mysql":
        return conn_cfg.database or ""
    return ""


@lru_cache(maxsize=256)
def _parse_definition(sql: str, dialect: str | None) -> exp.Expression:
    return sqlglot.parse_one(sql, read=dialect)


def parse_single(sql: str, dialect: str | None) -> exp.Expression:
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except ParseError as e:
        raise VirtualObjectError(f"Could not parse SQL: {_first_line(str(e))}") from e
    if len(statements) != 1:
        raise VirtualObjectError("Exactly one SQL statement is expected")
    return statements[0]


def _first_line(msg: str) -> str:
    return msg.strip().splitlines()[0] if msg.strip() else msg


def render(tree: exp.Expression, dialect: str | None) -> str:
    # Named placeholders stay `:name`: connectors bind parameters by that
    # spelling, while sqlglot would re-spell them per dialect (%(name)s, @name).
    for ph in list(tree.find_all(exp.Placeholder)):
        if ph.name and ph.name != "?":
            ph.replace(exp.Var(this=f":{ph.name}"))
    # normalize_functions=False keeps function names as written: upper-casing a
    # quoted/case-sensitive routine name would change what it resolves to.
    return tree.sql(dialect=dialect, normalize_functions=False, comments=False)


@dataclass
class _State:
    ctx: DialectContext
    objects: VirtualObjectSet
    now: datetime
    steps: list[MaterializeStep] = field(default_factory=list)
    used: list[VirtualObject] = field(default_factory=list)
    temp_for: dict[str, str] = field(default_factory=dict)
    hoisted: list[exp.CTE] = field(default_factory=list)
    recursive: bool = False
    taken: set[str] = field(default_factory=set)

    def mark_used(self, obj: VirtualObject) -> None:
        if all(o.id != obj.id for o in self.used):
            self.used.append(obj)


def expand(
    query: str,
    ctx: DialectContext,
    objects: VirtualObjectSet,
    *,
    now: datetime | None = None,
) -> ExpansionPlan:
    """Plan the execution of ``query`` against ``objects``."""
    if not objects or not objects.mentioned_in(query):
        return ExpansionPlan(sql=query)

    root = parse_single(query, ctx.dialect)
    state = _State(
        ctx=ctx,
        objects=objects,
        now=now or now_in(ctx.tz),
        taken={t.name.lower() for t in root.find_all(exp.Table)}
        | {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
        | set(objects.by_name),
    )
    _expand_tree(root, state, stack=())
    if not state.used:
        # The name only appeared in a literal, a column, or a CTE of the same name.
        return ExpansionPlan(sql=query)

    if state.hoisted:
        if "with_" not in root.arg_types:
            raise VirtualObjectError("This statement shape cannot reference a custom query")
        existing = root.args.get("with_")
        if existing is not None:
            existing.set("expressions", state.hoisted + list(existing.expressions))
            if state.recursive:
                existing.set("recursive", True)
        else:
            root.set("with_", exp.With(expressions=state.hoisted, recursive=state.recursive or None))

    return ExpansionPlan(
        sql=render(root, ctx.dialect),
        steps=state.steps,
        used=state.used,
        noop=False,
    )


def _split_bracketed(table: exp.Table) -> tuple[str, str, str]:
    """(catalog, db, name), undoing ``[dbo.sales]`` — one quoted identifier
    holding a dotted path, as naive quoting of a qualified name produces."""
    ident = table.this
    name, db, catalog = ident.name, table.db, table.catalog
    if not db and not catalog and ident.quoted and "." in name:
        parts = name.split(".")
        name = parts[-1]
        db = parts[-2] if len(parts) >= 2 else ""
        catalog = parts[-3] if len(parts) >= 3 else ""
    return catalog, db, name


def _resolve(table: exp.Table, state: _State, cte_names: set[str]) -> tuple[VirtualObject, str, str, str] | None:
    if not isinstance(table.this, exp.Identifier):
        return None  # table function, e.g. OPENJSON(...)
    catalog, db, name = _split_bracketed(table)
    if not db and not catalog and name.lower() in cte_names:
        return None  # a CTE of the same name shadows the object
    obj = state.objects.get(name)
    if obj is None:
        return None
    if db and db.lower() != state.ctx.schema.lower():
        return None
    if catalog and catalog.lower() != state.ctx.database.lower():
        return None
    return obj, catalog, db, name


def _expand_tree(tree: exp.Expression, state: _State, stack: tuple[str, ...]) -> None:
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    replaced: list[tuple[str, str, str]] = []

    for table in list(tree.find_all(exp.Table)):
        hit = _resolve(table, state, cte_names)
        if hit is None:
            continue
        obj, catalog, db, name = hit

        alias = table.args.get("alias")
        if alias is None:
            alias = exp.TableAlias(this=exp.Identifier(this=name, quoted=table.this.quoted))
        else:
            alias = alias.copy()

        node = _replacement(obj, alias, state, stack)
        pivots = table.args.get("pivots")
        if pivots:
            node.set("pivots", pivots)
        table.replace(node)
        state.mark_used(obj)
        replaced.append((catalog, db, name))

    if replaced:
        _fix_qualified_columns(tree, replaced)


def _fix_qualified_columns(tree: exp.Expression, replaced: list[tuple[str, str, str]]) -> None:
    """``dbo.sales.amount`` → ``sales.amount``: the schema-qualified column
    reference pointed at the table, which is now a derived table named after it."""
    for col in tree.find_all(exp.Column):
        tbl = col.table
        if not tbl:
            continue
        for catalog, db, name in replaced:
            dotted = ".".join(p for p in (catalog, db, name) if p)
            if tbl.lower() == dotted.lower() and "." in tbl:
                col.set("table", exp.to_identifier(name))
                col.set("db", None)
                col.set("catalog", None)
            elif tbl.lower() == name.lower() and (col.args.get("db") or col.args.get("catalog")):
                col.set("db", None)
                col.set("catalog", None)


def _replacement(
    obj: VirtualObject, alias: exp.TableAlias, state: _State, stack: tuple[str, ...]
) -> exp.Expression:
    if obj.status == "error" and not obj.columns:
        raise VirtualObjectError(f"'{obj.name}' is not usable: {obj.last_error or 'invalid definition'}")

    if obj.kind == KIND_QUERY:
        return _expand_query_object(obj, alias, state, stack)
    if obj.kind == KIND_PROCEDURE and obj.routine_type == ROUTINE_PG_FUNCTION:
        if state.ctx.db_type != "postgresql":
            raise VirtualObjectError(f"'{obj.name}' can only be used on PostgreSQL")
        return _pg_function_call(obj, alias, state)
    if obj.kind == KIND_PROCEDURE and obj.routine_type == ROUTINE_MSSQL_PROCEDURE:
        if state.ctx.db_type != "mssql":
            raise VirtualObjectError(f"'{obj.name}' can only be used on SQL Server")
        return _mssql_temp_table(obj, alias, state)
    raise VirtualObjectError(f"'{obj.name}' has an unsupported definition")


def _expand_query_object(
    obj: VirtualObject, alias: exp.TableAlias, state: _State, stack: tuple[str, ...]
) -> exp.Expression:
    if obj.key in stack:
        chain = " → ".join([*stack, obj.key])
        raise VirtualObjectError(f"Custom queries reference each other in a cycle: {chain}")
    if len(stack) >= MAX_DEPTH:
        raise VirtualObjectError(f"Custom queries are nested more than {MAX_DEPTH} levels deep")
    if not obj.normalized_sql:
        raise VirtualObjectError(f"'{obj.name}' has no SQL definition")

    inner = _parse_definition(obj.normalized_sql, state.ctx.dialect).copy()
    _expand_tree(inner, state, stack + (obj.key,))

    with_ = inner.args.get("with_")
    if with_ is not None:
        inner.set("with_", None)
        _hoist(with_, inner, state)

    return exp.Subquery(this=inner, alias=alias)


def _hoist(with_: exp.With, body: exp.Expression, state: _State) -> None:
    """Move a definition's CTEs to the statement's WITH.

    Every hoisted CTE is renamed to a private ``mv<n>_<name>``: once it sits in
    the statement's WITH it is visible to the caller's whole query, where its
    original name could shadow a real table the caller joins (a definition's
    ``orders`` CTE vs. the database's ``orders`` table). References inside the
    definition keep their original name as the alias, so qualified columns
    still resolve.
    """
    if with_.args.get("recursive"):
        state.recursive = True
    ctes = list(with_.expressions)
    for cte in ctes:
        old = cte.alias_or_name
        n = len(state.hoisted) + 1
        new = f"mv{n}_{old}"
        while new.lower() in state.taken:
            n += 1
            new = f"mv{n}_{old}"
        state.taken.add(new.lower())
        cte_alias = cte.args.get("alias")
        cte.set(
            "alias",
            exp.TableAlias(
                this=exp.to_identifier(new),
                columns=cte_alias.args.get("columns") if cte_alias is not None else None,
            ),
        )
        for scope in [body, *ctes]:
            for t in scope.find_all(exp.Table):
                if not t.db and isinstance(t.this, exp.Identifier) and t.name.lower() == old.lower():
                    if t.args.get("alias") is None:
                        t.set("alias", exp.TableAlias(this=exp.to_identifier(old)))
                    t.set("this", exp.to_identifier(new))
        state.hoisted.append(cte)


# ---------------------------------------------------------------- PostgreSQL

_SIMPLE_LOWER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _pg_ident(name: str) -> exp.Identifier:
    return exp.to_identifier(name, quoted=not _SIMPLE_LOWER.match(name))


def _pg_text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, (date, Decimal)):
        return str(v)
    return str(v)


def _pg_literal(value: Any, sql_type: str) -> exp.Expression:
    lit: exp.Expression = exp.Null() if value is None else exp.Literal.string(_pg_text(value))
    if not sql_type:
        return lit
    try:
        to = exp.DataType.build(sql_type, dialect="postgres")
    except Exception:
        return lit
    return exp.Cast(this=lit, to=to)


def _pg_function_call(obj: VirtualObject, alias: exp.TableAlias, state: _State) -> exp.Expression:
    resolved = resolve_params(obj.params, state.now)
    named = any(p.omit for p in obj.params)
    args: list[exp.Expression] = []
    for p in resolved:
        lit = _pg_literal(p.value, p.sql_type)
        args.append(exp.Kwarg(this=_pg_ident(p.name), expression=lit) if named else lit)

    fn_name = obj.routine_name or ""
    fn = exp.Anonymous(
        this=fn_name if _SIMPLE_LOWER.match(fn_name) else '"' + fn_name.replace('"', '""') + '"',
        expressions=args,
    )
    table = exp.Table(this=fn, alias=alias)
    if obj.routine_schema:
        table.set("db", _pg_ident(obj.routine_schema))
    return table


# ---------------------------------------------------------------- SQL Server


def _mssql_temp_table(obj: VirtualObject, alias: exp.TableAlias, state: _State) -> exp.Expression:
    temp = state.temp_for.get(obj.id)
    if temp is None:
        if not obj.columns:
            raise VirtualObjectError(f"'{obj.name}' has no known columns; refresh its definition")
        temp = f"#mv_{obj.id.replace('-', '')[:8].lower()}_{len(state.steps) + 1}"
        state.temp_for[obj.id] = temp
        params = [(p.name, p.value) for p in resolve_params(obj.params, state.now)]
        state.steps.append(
            MaterializeStep(obj=obj, temp_name=temp, params=params, mode=obj.materialization)
        )
    node = exp.to_table(temp, dialect="tsql")
    node.set("alias", alias)
    return node
