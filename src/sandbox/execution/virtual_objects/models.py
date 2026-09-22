"""
Virtual object data model.

A virtual object is a named relation that does not exist in the database but
behaves like a table everywhere the sandbox exposes one: the catalog lists it,
the column/sample sync describes it, and SQL that references it by name is
expanded before execution. Callers (and the LLM writing their SQL) never learn
how it is backed.

Two kinds:

* ``QUERY``     – a SELECT the admin wrote; inlined as a derived table.
* ``PROCEDURE`` – a routine whose result set is the relation:
    - ``mssql_procedure``: a SQL Server stored procedure, materialized into a
      session temp table (``INSERT INTO #t EXEC ...``) before the query runs;
    - ``pg_function``: a Postgres set-returning function, inlined as
      ``schema.fn(args)`` in the FROM clause.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

VirtualKind = Literal["QUERY", "PROCEDURE"]
RoutineType = Literal["mssql_procedure", "pg_function"]
Materialization = Literal["insert_exec", "client"]

KIND_QUERY = "QUERY"
KIND_PROCEDURE = "PROCEDURE"
ROUTINE_MSSQL_PROCEDURE = "mssql_procedure"
ROUTINE_PG_FUNCTION = "pg_function"


@dataclass(frozen=True)
class ParamSpec:
    """One routine parameter as configured by the admin.

    ``value`` is either a literal (``"2024-01-01"``, ``"42"``) or a date token
    (``"{{start_of_month}}"``, ``"{{today-7d}}"``) resolved at execution time.
    ``omit`` leaves the parameter out of the call so the routine's own default
    applies.
    """

    name: str
    sql_type: str = ""
    value: str | None = None
    omit: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ParamSpec":
        return cls(
            name=str(d.get("name") or ""),
            sql_type=str(d.get("sql_type") or ""),
            value=None if d.get("value") is None else str(d.get("value")),
            omit=bool(d.get("omit", False)),
        )


@dataclass(frozen=True)
class VirtualColumn:
    """A column of the virtual relation.

    ``name`` is what SQL refers to; ``source_name`` is what the routine emits
    (they differ only when the routine returned a blank or duplicate name).
    ``sql_type`` is the full database type (``nvarchar(50)``, ``decimal(18,2)``)
    and drives the temp-table DDL for SQL Server procedures.
    """

    name: str
    sql_type: str = ""
    nullable: bool = True
    source_name: str | None = None
    shape_source: str = "describe"  # describe | inferred | edited

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VirtualColumn":
        return cls(
            name=str(d.get("name") or ""),
            sql_type=str(d.get("sql_type") or d.get("type") or ""),
            nullable=bool(d.get("nullable", True)),
            source_name=d.get("source_name"),
            shape_source=str(d.get("shape_source") or "describe"),
        )


@dataclass
class VirtualObject:
    id: str
    connection_id: str
    kind: VirtualKind
    name: str
    description: str | None = None
    # QUERY
    sql_text: str | None = None
    normalized_sql: str | None = None
    # PROCEDURE
    routine_type: RoutineType | None = None
    routine_schema: str | None = None
    routine_name: str | None = None
    routine_signature: str | None = None
    params: list[ParamSpec] = field(default_factory=list)
    result_set_index: int = 0
    materialization: Materialization = "insert_exec"
    # Shape + behaviour
    columns: list[VirtualColumn] = field(default_factory=list)
    cache_ttl_seconds: int = 0
    definition_hash: str = ""
    status: str = "ok"
    last_error: str | None = None
    last_validated_at: datetime | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def key(self) -> str:
        return self.name.lower()

    @property
    def is_mssql_procedure(self) -> bool:
        return self.kind == KIND_PROCEDURE and self.routine_type == ROUTINE_MSSQL_PROCEDURE

    def compute_definition_hash(self) -> str:
        payload = {
            "kind": self.kind,
            "sql": self.normalized_sql,
            "routine": [self.routine_type, self.routine_schema, self.routine_name, self.routine_signature],
            "params": [asdict(p) for p in self.params],
            "rs": self.result_set_index,
            "mat": self.materialization,
            "cols": [[c.name, c.sql_type] for c in self.columns],
        }
        raw = json.dumps(payload, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).hexdigest()[:32]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "connection_id": self.connection_id,
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "sql_text": self.sql_text,
            "routine_type": self.routine_type,
            "routine_schema": self.routine_schema,
            "routine_name": self.routine_name,
            "routine_signature": self.routine_signature,
            "params": [asdict(p) for p in self.params],
            "result_set_index": self.result_set_index,
            "materialization": self.materialization,
            "columns": [asdict(c) for c in self.columns],
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "definition_hash": self.definition_hash,
            "status": self.status,
            "last_error": self.last_error,
            "last_validated_at": _iso(self.last_validated_at),
            "created_by": self.created_by,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
        }


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None


@dataclass
class MaterializeStep:
    """Fill a session temp table from a SQL Server procedure before the query.

    ``params`` are already resolved and ordered ``(name, python_value)``.
    ``cached_rows`` (set by the TTL cache) replaces executing the procedure;
    ``fetched_rows`` is filled by the connector in ``client`` mode so the
    executor can populate the cache afterwards.
    """

    obj: VirtualObject
    temp_name: str
    params: list[tuple[str, Any]]
    mode: Materialization
    cached_rows: list[tuple[Any, ...]] | None = None
    fetched_rows: list[tuple[Any, ...]] | None = None


@dataclass
class ExpansionPlan:
    """What to run instead of the caller's SQL.

    ``noop`` means no virtual object was referenced and ``sql`` is the
    caller's query byte-for-byte.
    """

    sql: str
    steps: list[MaterializeStep] = field(default_factory=list)
    used: list[VirtualObject] = field(default_factory=list)
    noop: bool = True
