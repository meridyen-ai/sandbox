"""
In-process index of virtual objects per connection.

Every SQL execution consults it, so it is cached: invalidated on every CRUD
write in this process and re-read after ``_TTL_SECONDS`` so other workers /
processes converge. Catalog listings ask for ``fresh=True`` — the data-analyst
catalog sync is authoritative and must never see a stale or partial set.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field

from sandbox.core.logging import get_logger
from sandbox.execution.virtual_objects.models import VirtualObject

logger = get_logger(__name__)

_TTL_SECONDS = 10.0


@dataclass
class VirtualObjectSet:
    """Objects of one connection, keyed by lower-cased name."""

    by_name: dict[str, VirtualObject] = field(default_factory=dict)
    _pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False)

    def __bool__(self) -> bool:
        return bool(self.by_name)

    def get(self, name: str) -> VirtualObject | None:
        return self.by_name.get(name.lower())

    def mentioned_in(self, sql: str) -> bool:
        """Cheap pre-check: could ``sql`` reference any object at all?

        False means the query is guaranteed not to need expansion, and is
        passed to the database byte-for-byte without being parsed.
        """
        if not self.by_name:
            return False
        if self._pattern is None:
            alts = "|".join(
                re.escape(n) for n in sorted(self.by_name, key=len, reverse=True)
            )
            self._pattern = re.compile(rf"(?<![\w$#@]){'(?:' + alts + ')'}(?![\w$])", re.IGNORECASE)
        return self._pattern.search(sql) is not None

    def with_object(self, obj: VirtualObject) -> "VirtualObjectSet":
        """Copy with ``obj`` added or replaced (used to describe/preview drafts)."""
        by_name = {k: v for k, v in self.by_name.items() if v.id != obj.id}
        by_name[obj.key] = obj
        return VirtualObjectSet(by_name)


class VirtualObjectRegistry:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, VirtualObjectSet]] = {}

    def invalidate(self, connection_id: str | None = None) -> None:
        if connection_id is None:
            self._cache.clear()
        else:
            self._cache.pop(connection_id, None)

    def _load(self, connection_id: str) -> VirtualObjectSet:
        from sandbox.core import virtual_object_store as store

        objects = store.list_for_connection(connection_id)
        return VirtualObjectSet({o.key: o for o in objects})

    async def get(self, connection_id: str, *, fresh: bool = False) -> VirtualObjectSet:
        """Objects of ``connection_id``.

        ``fresh=True`` always reads the store and raises if it cannot. Otherwise
        a store failure falls back to the last known set (or none), so queries
        that do not touch virtual objects keep working if the store is down.
        """
        now = time.monotonic()
        cached = self._cache.get(connection_id)
        if not fresh and cached and now - cached[0] < _TTL_SECONDS:
            return cached[1]
        try:
            objs = await asyncio.to_thread(self._load, connection_id)
        except Exception as e:
            if fresh:
                raise
            logger.warning("virtual_objects_load_failed", connection=connection_id, error=str(e))
            return cached[1] if cached else VirtualObjectSet()
        self._cache[connection_id] = (now, objs)
        return objs


registry = VirtualObjectRegistry()
