"""
Optional TTL cache of procedure result sets.

Reporting procedures are often expensive and their output rarely changes
minute to minute, while an agent answering one question may query the same
object several times. An object with ``cache_ttl_seconds > 0`` has its rows
kept here, keyed by the definition and the *resolved* parameter values — so a
``{{today}}`` parameter naturally misses once the day rolls over.

v1 scope: SQL Server procedures. A cached step is always run in ``client``
mode — the rows are fetched into the sandbox on a miss, and bulk-inserted
into the session temp table on a hit.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from cachetools import LRUCache
from prometheus_client import Counter

from sandbox.execution.virtual_objects.models import ExpansionPlan, MaterializeStep

MAX_ENTRIES = 64
MAX_ROWS = 50_000

_lookups = Counter(
    "sandbox_virtual_object_cache_lookups_total",
    "Procedure result cache lookups for virtual objects",
    ["result"],
)


def _key(step: MaterializeStep) -> tuple[Any, ...]:
    return (
        step.obj.id,
        step.obj.definition_hash,
        tuple((name, repr(value)) for name, value in step.params),
    )


class ResultCache:
    def __init__(self, max_entries: int = MAX_ENTRIES, max_rows: int = MAX_ROWS) -> None:
        self._entries: LRUCache = LRUCache(maxsize=max_entries)
        self._lock = threading.Lock()
        self.max_rows = max_rows

    def attach(self, plan: ExpansionPlan) -> None:
        """Serve cacheable steps from the cache; mark misses for fetching."""
        now = time.monotonic()
        for step in plan.steps:
            if step.obj.cache_ttl_seconds <= 0:
                continue
            step.mode = "client"
            with self._lock:
                entry = self._entries.get(_key(step))
            if entry and entry[0] > now:
                step.cached_rows = entry[1]
                _lookups.labels("hit").inc()
            else:
                _lookups.labels("miss").inc()

    def store(self, plan: ExpansionPlan) -> None:
        now = time.monotonic()
        for step in plan.steps:
            ttl = step.obj.cache_ttl_seconds
            if ttl <= 0 or step.cached_rows is not None or step.fetched_rows is None:
                continue
            if step.obj.id.startswith("draft-"):
                continue  # previews of unsaved definitions
            if len(step.fetched_rows) > self.max_rows:
                continue
            with self._lock:
                self._entries[_key(step)] = (now + ttl, step.fetched_rows)

    def invalidate(self, object_id: str) -> None:
        with self._lock:
            for key in [k for k in self._entries if k[0] == object_id]:
                self._entries.pop(key, None)


result_cache = ResultCache()
