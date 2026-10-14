"""What deleting a knowledge-base document removes besides its rows.

A document's passages live in the knowledge base's LlamaIndex vector tables
(``data_llamaindex_kb_{kb}`` for the legacy 1536-wide vectors and
``data_llamaindex_kb_{kb}_e{dim}`` for each local model width), tagged with
the stored file's id; its bytes live under ``/app/data/documents/{space}/``
named ``{file_id}{ext}`` (plus anything derived from it, which starts with the
same id). Without removing both, a deleted document kept answering searches
and kept its storage.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, List, Optional

_FILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def vector_tables_for(kb_id: Any, table_names: Iterable[str]) -> List[str]:
    """Of ``table_names``, the vector tables of knowledge base ``kb_id``.

    Exact names only: ``kb_1`` must not reach ``kb_12``. The names come from
    the catalog and are interpolated into SQL, so anything else is ignored.
    """
    kb = int(kb_id)
    pattern = re.compile(rf"^data_llamaindex_kb_{kb}(?:_e\d+)?$")
    return sorted({name for name in table_names if pattern.match(str(name))})


def remove_stored_files(root: Path, space: Optional[str], file_id: Any) -> int:
    """Delete the stored file(s) of ``file_id`` inside ``space``'s directory.
    Returns how many files were removed. An id that is not a plain token
    removes nothing (it would be a glob)."""
    value = str(file_id or "")
    if not _FILE_ID_RE.match(value) or not space:
        return 0
    base = Path(root) / space
    if not base.is_dir():
        return 0
    removed = 0
    for path in base.rglob(f"{value}*"):
        if path.is_file():
            path.unlink(missing_ok=True)
            removed += 1
    return removed
