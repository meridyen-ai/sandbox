"""
Errors for virtual objects, and scrubbing of database errors.

Whoever wrote the SQL (usually an LLM) must only ever see the virtual object's
name. A database error raised while running the expanded batch can mention
the procedure, the session temp table or the INSERT…EXEC wrapper; ``sanitize``
rewrites those back to the object name before the message leaves the sandbox.
"""

from __future__ import annotations

import re
from typing import Iterable

from sandbox.core.exceptions import ValidationError
from sandbox.execution.virtual_objects.models import ExpansionPlan, VirtualObject


class VirtualObjectError(ValidationError):
    """A virtual object definition or reference is invalid."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, **kwargs)
        self.error_code = "VIRTUAL_OBJECT_ERROR"


_TEMP_RE = re.compile(r"#mv_[0-9a-z]+_\d+", re.IGNORECASE)
_INSERT_EXEC_RE = re.compile(r"\bINSERT(\s+INTO)?\s+(<virtual table>\s+)?EXEC(UTE)?\b", re.IGNORECASE)


def _routine_patterns(obj: VirtualObject) -> Iterable[re.Pattern[str]]:
    if not obj.routine_name:
        return []
    name = re.escape(obj.routine_name)
    schema = re.escape(obj.routine_schema or "")
    parts = []
    if schema:
        parts.append(rf"[\[\"`]?{schema}[\]\"`]?\s*\.\s*[\[\"`]?{name}[\]\"`]?")
    parts.append(rf"[\[\"`]?{name}[\]\"`]?")
    return [re.compile(rf"(?<![\w]){p}(?![\w])", re.IGNORECASE) for p in parts]


def sanitize(message: str, plan: ExpansionPlan | None) -> str:
    """Replace routine/temp-table names in ``message`` with object names."""
    if not plan or plan.noop or not message:
        return message
    out = message
    for step in plan.steps:
        out = re.sub(re.escape(step.temp_name), step.obj.name, out, flags=re.IGNORECASE)
    for obj in plan.used:
        for pat in _routine_patterns(obj):
            out = pat.sub(obj.name, out)
    out = _TEMP_RE.sub("<virtual table>", out)
    out = _INSERT_EXEC_RE.sub("materialization", out)
    return out
