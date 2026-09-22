"""
Run SQL that may reference virtual objects: expand → (cache) → execute.

The single entry point every sandbox code path uses to run caller SQL, so
execution, sample rows, previews and describes all resolve virtual objects
the same way.
"""

from __future__ import annotations

from typing import Any

from sandbox.connectors.base import QueryResult
from sandbox.core.exceptions import SQLExecutionError
from sandbox.execution.virtual_objects.cache import result_cache
from sandbox.execution.virtual_objects.errors import VirtualObjectError, sanitize
from sandbox.execution.virtual_objects.expander import context_for, expand
from sandbox.execution.virtual_objects.models import ExpansionPlan
from sandbox.execution.virtual_objects.registry import VirtualObjectSet, registry


async def plan_query(
    conn_cfg: Any, sql: str, objects: VirtualObjectSet | None = None
) -> ExpansionPlan:
    objs = objects if objects is not None else await registry.get(conn_cfg.id)
    plan = expand(sql, context_for(conn_cfg), objs)
    if plan.steps:
        result_cache.attach(plan)
    return plan


async def execute_plan(
    connector: Any,
    conn: Any,
    plan: ExpansionPlan,
    *,
    original_sql: str,
    parameters: dict[str, Any] | None = None,
) -> QueryResult:
    """Execute ``plan``; errors come back scrubbed and quoting ``original_sql``."""
    if plan.noop:
        return await connector.execute(conn, plan.sql, parameters)
    try:
        result = await connector.execute_plan(conn, plan, parameters)
    except VirtualObjectError:
        raise
    except Exception as e:
        message = getattr(e, "message", None) or str(e)
        raise SQLExecutionError(sanitize(message, plan), query=original_sql) from None
    result_cache.store(plan)
    return result


async def run(
    connector: Any,
    conn: Any,
    conn_cfg: Any,
    sql: str,
    *,
    parameters: dict[str, Any] | None = None,
    objects: VirtualObjectSet | None = None,
) -> QueryResult:
    plan = await plan_query(conn_cfg, sql, objects)
    return await execute_plan(connector, conn, plan, original_sql=sql, parameters=parameters)
