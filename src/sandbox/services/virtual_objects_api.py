"""
REST API for virtual objects — custom queries and stored procedures that the
rest of the platform sees as tables.

Every write validates the definition against the live database (name free,
routine exists and is executable, SQL parses and passes the validator),
describes the resulting columns, and for SQL Server procedures decides how
they are materialized. Nothing is stored unless all of that succeeds.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from sandbox.core import virtual_object_store as store
from sandbox.core.config import DatabaseConnectionConfig, get_config
from sandbox.core.logging import get_logger
from sandbox.execution.virtual_objects.cache import result_cache
from sandbox.execution.virtual_objects.errors import VirtualObjectError
from sandbox.execution.virtual_objects.expander import DialectContext, context_for, expand
from sandbox.execution.virtual_objects.models import (
    KIND_PROCEDURE,
    KIND_QUERY,
    ROUTINE_MSSQL_PROCEDURE,
    ROUTINE_PG_FUNCTION,
    ParamSpec,
    VirtualColumn,
    VirtualObject,
)
from sandbox.execution.virtual_objects.registry import VirtualObjectSet, registry
from sandbox.execution.virtual_objects.runner import execute_plan
from sandbox.execution.virtual_objects.tokens import (
    convert_value,
    describe_tokens,
    now_in,
    resolve_params,
)
from sandbox.execution.virtual_objects.validation import (
    NAME_RE,
    normalize_query_definition,
    unique_column_names,
    validate_name,
    validate_routine_name,
    validate_sql_type,
)
from sandbox.services.schema_sql import build_sample_query

logger = get_logger(__name__)

PROCEDURE_DB_TYPES = {"mssql": ROUTINE_MSSQL_PROCEDURE, "postgresql": ROUTINE_PG_FUNCTION}
DESCRIBE_SAMPLE_ROWS = 200
OPERATION_TIMEOUT_SECONDS = 300


# ---------------------------------------------------------------- models


class ParamIn(BaseModel):
    name: str
    sql_type: str = ""
    value: str | None = None
    omit: bool = False


class ColumnIn(BaseModel):
    name: str
    sql_type: str = ""
    source_name: str | None = None


class VirtualObjectIn(BaseModel):
    kind: Literal["QUERY", "PROCEDURE"]
    name: str
    description: str | None = None
    sql_text: str | None = None
    routine_schema: str | None = None
    routine_name: str | None = None
    routine_signature: str | None = None
    params: list[ParamIn] = Field(default_factory=list)
    result_set_index: int = Field(0, ge=0, le=20)
    cache_ttl_seconds: int = Field(0, ge=0, le=86400)
    # Admin overrides of column types (e.g. inferred nvarchar(max) → date).
    columns: list[ColumnIn] | None = None
    created_by: str | None = None


class PreviewIn(VirtualObjectIn):
    limit: int = Field(20, ge=1, le=100)
    # Previewing an edit of an existing object: exclude it from collision checks.
    object_id: str | None = None


# ---------------------------------------------------------------- helpers


def _connection(connection_id: str) -> DatabaseConnectionConfig:
    cfg = get_config().get_connection(connection_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Connection '{connection_id}' not found")
    return cfg


def _connector(cfg: DatabaseConnectionConfig):
    from sandbox.connectors.factory import get_connector

    return get_connector(cfg.db_type, cfg)


def _draft(body: VirtualObjectIn, cfg: DatabaseConnectionConfig, existing: VirtualObject | None) -> VirtualObject:
    """Build (unvalidated) object from the request."""
    obj = VirtualObject(
        id=existing.id if existing else f"draft-{uuid.uuid4().hex}",
        connection_id=cfg.id,
        kind=body.kind,
        name=existing.name if existing else body.name.strip(),
        description=body.description,
        cache_ttl_seconds=body.cache_ttl_seconds,
        created_by=existing.created_by if existing else body.created_by,
        created_at=existing.created_at if existing else None,
    )
    if body.kind == KIND_QUERY:
        obj.sql_text = body.sql_text
    else:
        obj.routine_type = PROCEDURE_DB_TYPES.get(cfg.db_type.value)
        obj.routine_schema = (body.routine_schema or "").strip() or None
        obj.routine_name = (body.routine_name or "").strip() or None
        obj.routine_signature = body.routine_signature
        obj.params = [ParamSpec(p.name.strip().lstrip("@"), p.sql_type.strip(), p.value, p.omit) for p in body.params]
        obj.result_set_index = body.result_set_index
    return obj


def _check_static(obj: VirtualObject, ctx: DialectContext) -> None:
    """Everything that can be checked without the database."""
    validate_name(obj.name, ctx)
    if obj.kind == KIND_QUERY:
        obj.normalized_sql = normalize_query_definition(obj.sql_text or "", ctx)
        obj.cache_ttl_seconds = 0
        return

    if obj.routine_type is None:
        raise VirtualObjectError(
            "Stored procedures can be used as tables on SQL Server and PostgreSQL only"
        )
    validate_routine_name(obj.routine_schema, "schema")
    validate_routine_name(obj.routine_name, "procedure name")
    now = now_in(ctx.tz)
    is_pg = obj.routine_type == ROUTINE_PG_FUNCTION
    # Postgres functions may have unnamed arguments (passed positionally);
    # omitting any argument switches to named notation, which needs names.
    names_required = not is_pg or any(p.omit for p in obj.params)
    names = set()
    for p in obj.params:
        if p.name or names_required:
            if not NAME_RE.match(p.name):
                raise VirtualObjectError(
                    f"Invalid parameter name '{p.name}'"
                    + (" (unnamed arguments cannot be omitted)" if is_pg and not p.name else "")
                )
            if p.name.lower() in names:
                raise VirtualObjectError(f"Parameter '{p.name}' is listed twice")
            names.add(p.name.lower())
        validate_sql_type(p.sql_type, f"parameter '{p.name}'")
        if not p.omit:
            convert_value(p.value, p.sql_type, now)  # raises on a bad literal/token
    if is_pg:
        obj.cache_ttl_seconds = 0  # v1: result caching is SQL Server only
        obj.materialization = "insert_exec"


async def _check_name_free(connector, conn, cfg, obj: VirtualObject, objects: VirtualObjectSet) -> None:
    other = objects.get(obj.name)
    if other is not None and other.id != obj.id:
        raise VirtualObjectError(f"A custom object named '{obj.name}' already exists", field="name")
    entries = await connector.get_table_entries(conn, schema=cfg.schema_name)
    if any(e["name"].lower() == obj.name.lower() for e in entries):
        raise VirtualObjectError(
            f"A table or view named '{obj.name}' already exists in this schema", field="name"
        )


async def _find_routine(connector, conn, obj: VirtualObject) -> dict[str, Any]:
    try:
        routines = await connector.list_routines(
            conn, schema=obj.routine_schema, search=obj.routine_name
        )
    except NotImplementedError as e:
        raise VirtualObjectError(str(e))
    for r in routines:
        if r["name"] == obj.routine_name and r["schema"] == obj.routine_schema:
            if obj.routine_type == ROUTINE_PG_FUNCTION and obj.routine_signature is not None:
                if r.get("signature") != obj.routine_signature:
                    continue
            return r
    raise VirtualObjectError(
        f"'{obj.routine_schema}.{obj.routine_name}' was not found, or this connection's "
        "login lacks permission to execute it"
    )


# pymssql's coarse type codes, for a column whose values were all NULL (or the
# run returned no rows): enough to keep numbers numeric until an admin refines it.
_TYPE_CODE_FALLBACK = {
    "NUMBER": "float",
    "DECIMAL": "decimal(38,6)",
    "DATETIME": "datetime2",
    "BINARY": "varbinary(max)",
}


def _inferred_type(values: list[Any], type_code: str | None = None) -> str:
    from datetime import date as _date, datetime as _datetime, time as _time
    from decimal import Decimal
    from uuid import UUID

    sample = next((v for v in values if v is not None), None)
    if sample is None:
        return _TYPE_CODE_FALLBACK.get(type_code or "", "nvarchar(max)")
    if isinstance(sample, bool):
        return "bit"
    if isinstance(sample, int):
        return "bigint"
    if isinstance(sample, float):
        return "float"
    if isinstance(sample, Decimal):
        scale = max(
            (-v.as_tuple().exponent for v in values if isinstance(v, Decimal) and v.is_finite()),
            default=0,
        )
        return f"decimal(38,{min(max(scale, 0), 12)})"
    if isinstance(sample, _datetime):
        return "datetimeoffset" if sample.tzinfo else "datetime2"
    if isinstance(sample, _date):
        return "date"
    if isinstance(sample, _time):
        return "time"
    if isinstance(sample, (bytes, bytearray)):
        return "varbinary(max)"
    if isinstance(sample, UUID):
        return "uniqueidentifier"
    return "nvarchar(max)"


def _apply_column_overrides(
    described: list[VirtualColumn], overrides: list[ColumnIn] | None
) -> list[VirtualColumn]:
    if not overrides:
        return described
    if len(overrides) != len(described):
        return described  # the procedure's shape changed; the edit no longer applies
    out = []
    for col, ov in zip(described, overrides):
        sql_type = ov.sql_type.strip() or col.sql_type
        validate_sql_type(sql_type, f"column '{col.name}'")
        edited = sql_type != col.sql_type
        out.append(VirtualColumn(
            name=col.name,
            sql_type=sql_type,
            nullable=True,
            source_name=col.source_name,
            shape_source="edited" if edited else col.shape_source,
        ))
    return out


async def _describe(
    connector, conn, cfg, obj: VirtualObject, objects: VirtualObjectSet, overrides: list[ColumnIn] | None
) -> list[str]:
    """Fill ``obj.columns`` (and materialization for SQL Server procedures).

    Returns warnings for the UI.
    """
    ctx = context_for(cfg)
    warnings: list[str] = []

    if obj.kind == KIND_QUERY or obj.routine_type == ROUTINE_PG_FUNCTION:
        if obj.routine_type == ROUTINE_PG_FUNCTION:
            await _find_routine(connector, conn, obj)
        probe = expand(f"SELECT * FROM {obj.name} WHERE 1 = 0", ctx, objects.with_object(obj))
        described = None
        if not probe.steps:
            described = await connector.describe_sql(conn, probe.sql)
        if described is None:
            result = await execute_plan(connector, conn, probe, original_sql=probe.sql)
            described = [
                {"name": n, "sql_type": t, "nullable": True}
                for n, t in zip(result.columns, result.column_types)
            ]
        names = [d["name"] for d in described]
        if obj.kind == KIND_QUERY:
            if any(not (n or "").strip() for n in names):
                raise VirtualObjectError(
                    "Every column needs a name; add an alias to computed expressions "
                    "(e.g. SUM(amount) AS total_amount)"
                )
            dupes = sorted({n for n in names if names.count(n) > 1})
            if dupes:
                raise VirtualObjectError(
                    f"Column names must be unique; alias the duplicates: {', '.join(dupes)}"
                )
        obj.columns = [
            VirtualColumn(name=n, sql_type=d["sql_type"], nullable=d["nullable"], source_name=d["name"])
            for n, d in zip(unique_column_names(names), described)
        ]
        return warnings

    # SQL Server procedure. Run it once: it tells us how many result sets it
    # produces (INSERT…EXEC takes ALL of them, so a procedure with several must
    # be read client-side), and it is the fallback source of column types.
    await _find_routine(connector, conn, obj)
    params = [(p.name, p.value) for p in resolve_params(obj.params, now_in(ctx.tz))]
    sample = await connector.exec_procedure(conn, obj, params, DESCRIBE_SAMPLE_ROWS)
    described = None
    if obj.result_set_index == 0:
        described = await connector.describe_procedure(conn, obj.routine_schema, obj.routine_name)
    if described:
        names = unique_column_names([d["name"] for d in described])
        columns = [
            VirtualColumn(name=n, sql_type=d["sql_type"], nullable=True, source_name=d["name"] or None)
            for n, d in zip(names, described)
        ]
    else:
        # SQL Server cannot describe it statically (temp tables, dynamic SQL, a
        # later result set): infer types from the values it returned.
        result = sample
        names = unique_column_names(result.columns)
        columns = [
            VirtualColumn(
                name=n,
                sql_type=_inferred_type(
                    [row[i] for row in result.rows],
                    result.column_types[i] if i < len(result.column_types) else None,
                ),
                nullable=True,
                source_name=result.columns[i] or None,
                shape_source="inferred",
            )
            for i, n in enumerate(names)
        ]
        warnings.append(
            "Column types were inferred from the returned rows; review them before saving"
        )
    if not columns:
        raise VirtualObjectError("The procedure returned no columns")
    obj.columns = _apply_column_overrides(columns, overrides)

    if obj.cache_ttl_seconds > 0 or obj.result_set_index > 0 or sample.result_set_count > 1:
        obj.materialization = "client"
    else:
        ok, error = await connector.probe_insert_exec(conn, obj, params)
        if ok:
            obj.materialization = "insert_exec"
        elif error is None:
            obj.materialization = "client"
            warnings.append(
                "This procedure cannot run inside INSERT…EXEC; its rows are fetched "
                "through the sandbox instead (slower for very large results)"
            )
        else:
            raise VirtualObjectError(f"Running the procedure failed: {error}")
    return warnings


async def _validate_and_describe(
    cfg: DatabaseConnectionConfig,
    obj: VirtualObject,
    overrides: list[ColumnIn] | None,
) -> tuple[list[str], VirtualObjectSet]:
    ctx = context_for(cfg)
    _check_static(obj, ctx)
    objects = await registry.get(cfg.id, fresh=True)
    connector = _connector(cfg)

    async def _run() -> list[str]:
        async with connector.get_connection() as conn:
            await _check_name_free(connector, conn, cfg, obj, objects)
            return await _describe(connector, conn, cfg, obj, objects, overrides)

    try:
        warnings = await asyncio.wait_for(_run(), timeout=OPERATION_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise VirtualObjectError(f"Validating '{obj.name}' timed out")
    obj.definition_hash = obj.compute_definition_hash()
    obj.status = "ok"
    obj.last_error = None
    obj.last_validated_at = datetime.now(timezone.utc)
    return warnings, objects


def _changed(obj_id: str, connection_id: str) -> None:
    registry.invalidate(connection_id)
    result_cache.invalidate(obj_id)


def _error(e: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=getattr(e, "message", None) or str(e))


# ---------------------------------------------------------------- routes


def register_virtual_object_routes(app: FastAPI, verify_token: Callable) -> None:
    base = "/api/v1/connections/{connection_id}/virtual-objects"

    @app.get(base, tags=["Virtual Objects"])
    async def list_virtual_objects(connection_id: str, token_data: dict = Depends(verify_token)) -> JSONResponse:
        _connection(connection_id)
        objs = await asyncio.to_thread(store.list_for_connection, connection_id)
        return JSONResponse(content={"objects": [o.to_dict() for o in objs]})

    @app.get(base + "/{object_id}", tags=["Virtual Objects"])
    async def get_virtual_object(connection_id: str, object_id: str, token_data: dict = Depends(verify_token)) -> JSONResponse:
        obj = await asyncio.to_thread(store.get, object_id)
        if obj is None or obj.connection_id != connection_id:
            raise HTTPException(status_code=404, detail="Virtual object not found")
        return JSONResponse(content=obj.to_dict())

    @app.post(base, tags=["Virtual Objects"], status_code=201)
    async def create_virtual_object(
        connection_id: str, body: VirtualObjectIn, token_data: dict = Depends(verify_token)
    ) -> JSONResponse:
        cfg = _connection(connection_id)
        obj = _draft(body, cfg, None)
        try:
            warnings, _ = await _validate_and_describe(cfg, obj, body.columns)
        except VirtualObjectError as e:
            raise _error(e)
        except Exception as e:
            raise _error(e)
        obj.id = ""
        try:
            created = await asyncio.to_thread(store.create, obj)
        except Exception as e:
            if "ux_virtual_objects_conn_name" in str(e):
                raise HTTPException(status_code=409, detail=f"'{obj.name}' already exists")
            raise
        _changed(created.id, connection_id)
        logger.info("virtual_object_created", connection=connection_id, name=created.name, kind=created.kind)
        return JSONResponse(status_code=201, content={**created.to_dict(), "warnings": warnings})

    @app.put(base + "/{object_id}", tags=["Virtual Objects"])
    async def update_virtual_object(
        connection_id: str, object_id: str, body: VirtualObjectIn, token_data: dict = Depends(verify_token)
    ) -> JSONResponse:
        cfg = _connection(connection_id)
        existing = await asyncio.to_thread(store.get, object_id)
        if existing is None or existing.connection_id != connection_id:
            raise HTTPException(status_code=404, detail="Virtual object not found")
        if body.name.strip().lower() != existing.name.lower():
            raise HTTPException(
                status_code=400,
                detail="A custom object cannot be renamed; create a new one instead",
            )
        if body.kind != existing.kind:
            raise HTTPException(status_code=400, detail="The kind of a custom object cannot change")
        obj = _draft(body, cfg, existing)
        try:
            warnings, _ = await _validate_and_describe(cfg, obj, body.columns)
        except Exception as e:
            raise _error(e)
        updated = await asyncio.to_thread(store.update, obj)
        _changed(object_id, connection_id)
        logger.info("virtual_object_updated", connection=connection_id, name=obj.name)
        return JSONResponse(content={**updated.to_dict(), "warnings": warnings})

    @app.delete(base + "/{object_id}", tags=["Virtual Objects"])
    async def delete_virtual_object(
        connection_id: str, object_id: str, token_data: dict = Depends(verify_token)
    ) -> JSONResponse:
        existing = await asyncio.to_thread(store.get, object_id)
        if existing is None or existing.connection_id != connection_id:
            raise HTTPException(status_code=404, detail="Virtual object not found")
        await asyncio.to_thread(store.delete, object_id)
        _changed(object_id, connection_id)
        logger.info("virtual_object_deleted", connection=connection_id, name=existing.name)
        return JSONResponse(content={"deleted": True, "name": existing.name})

    @app.post(base + "/{object_id}/refresh", tags=["Virtual Objects"])
    async def refresh_virtual_object(
        connection_id: str, object_id: str, token_data: dict = Depends(verify_token)
    ) -> JSONResponse:
        """Re-describe after the underlying query/procedure changed."""
        cfg = _connection(connection_id)
        existing = await asyncio.to_thread(store.get, object_id)
        if existing is None or existing.connection_id != connection_id:
            raise HTTPException(status_code=404, detail="Virtual object not found")
        body = VirtualObjectIn(
            kind=existing.kind,
            name=existing.name,
            description=existing.description,
            sql_text=existing.sql_text,
            routine_schema=existing.routine_schema,
            routine_name=existing.routine_name,
            routine_signature=existing.routine_signature,
            params=[ParamIn(**asdict(p)) for p in existing.params],
            result_set_index=existing.result_set_index,
            cache_ttl_seconds=existing.cache_ttl_seconds,
            columns=[
                ColumnIn(name=c.name, sql_type=c.sql_type) for c in existing.columns
            ] if any(c.shape_source == "edited" for c in existing.columns) else None,
        )
        obj = _draft(body, cfg, existing)
        try:
            warnings, _ = await _validate_and_describe(cfg, obj, body.columns)
        except Exception as e:
            message = getattr(e, "message", None) or str(e)
            await asyncio.to_thread(store.set_status, object_id, "error", message)
            _changed(object_id, connection_id)
            raise HTTPException(status_code=400, detail=message)
        updated = await asyncio.to_thread(store.update, obj)
        _changed(object_id, connection_id)
        return JSONResponse(content={**updated.to_dict(), "warnings": warnings})

    @app.post(base + "/preview", tags=["Virtual Objects"])
    async def preview_virtual_object(
        connection_id: str, body: PreviewIn, token_data: dict = Depends(verify_token)
    ) -> JSONResponse:
        """Validate + describe + return sample rows. Stores nothing."""
        from sandbox.services.rest_api import _make_json_safe

        cfg = _connection(connection_id)
        existing = None
        if body.object_id:
            existing = await asyncio.to_thread(store.get, body.object_id)
            if existing is not None and existing.connection_id != connection_id:
                existing = None
        obj = _draft(body, cfg, existing)
        if existing is None:
            obj.name = body.name.strip()
        try:
            warnings, objects = await _validate_and_describe(cfg, obj, body.columns)
            connector = _connector(cfg)
            sql = build_sample_query(cfg.db_type.value, cfg.schema_name, obj.name, None, body.limit)
            plan = expand(sql, context_for(cfg), objects.with_object(obj))

            async def _run():
                async with connector.get_connection() as conn:
                    return await execute_plan(connector, conn, plan, original_sql=sql)

            result = await asyncio.wait_for(_run(), timeout=OPERATION_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=400, detail="Preview timed out")
        except Exception as e:
            raise _error(e)

        ctx = context_for(cfg)
        return JSONResponse(content={
            "columns": [
                {"name": c.name, "sql_type": c.sql_type, "shape_source": c.shape_source}
                for c in obj.columns
            ],
            "rows": [
                {col: _make_json_safe(v) for col, v in zip(result.columns, row)}
                for row in result.rows
            ],
            "resolved_params": [
                {"name": p.name, "value": _make_json_safe(p.value)}
                for p in resolve_params(obj.params, now_in(ctx.tz))
            ],
            "materialization": obj.materialization if obj.kind == KIND_PROCEDURE else None,
            "warnings": warnings,
        })

    @app.get("/api/v1/connections/{connection_id}/procedures", tags=["Virtual Objects"])
    async def list_procedures(
        connection_id: str,
        search: str | None = None,
        schema: str | None = None,
        token_data: dict = Depends(verify_token),
    ) -> JSONResponse:
        """Routines that can back a table: SQL Server procedures, Postgres SRFs."""
        cfg = _connection(connection_id)
        if cfg.db_type.value not in PROCEDURE_DB_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Stored procedures can be used as tables on SQL Server and PostgreSQL only",
            )
        connector = _connector(cfg)
        try:
            async with connector.get_connection() as conn:
                routines = await asyncio.wait_for(
                    connector.list_routines(conn, schema=schema or None, search=search or None),
                    timeout=60,
                )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Listing procedures timed out")
        except Exception as e:
            raise _error(e)
        return JSONResponse(content={"routines": routines})

    @app.get("/api/v1/virtual-objects/tokens", tags=["Virtual Objects"])
    async def list_tokens(
        connection_id: str | None = None, token_data: dict = Depends(verify_token)
    ) -> JSONResponse:
        from sandbox.execution.virtual_objects.tokens import resolve_timezone

        tz = resolve_timezone(_connection(connection_id).extra_params if connection_id else None)
        return JSONResponse(content={"timezone": str(tz), "tokens": describe_tokens(now_in(tz))})
