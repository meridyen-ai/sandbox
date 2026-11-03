"""Documents stored before a document call named its space.

An upload that named no space was written at the top of the store
(``/app/data/documents/{file_id}{ext}``) or under the upload's own folder
(``/app/data/documents/{folder}/{file_id}{ext}``), and the knowledge bases of
that time recorded no space. A document call now reads only inside its
space's folder and searches only knowledge bases of its space, so those files
and knowledge bases answered no one.

Only the backend knows which space owns each connection and file, so it
claims them: the space's files are linked into ``{space}/``, where its calls
read, and the knowledge bases made for its connections take its id. A file
inside another space's folder and a knowledge base that has a space are never
claimed. The original stays where it was, so a file two spaces use can be
claimed by both.
"""
from __future__ import annotations

import os
import shutil
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

from sqlalchemy import bindparam, text

_UUID_LEN = 36


def _stored_id(value: Any) -> str | None:
    """``value`` when it is a stored file's id: the sandbox names every stored
    file by a uuid4 it generated, so anything else (a prefix, a glob, a path)
    matches nothing."""
    s = str(value or "")
    try:
        return s if str(uuid.UUID(s)) == s else None
    except ValueError:
        return None


def _in_a_space_folder(rel: Path) -> bool:
    """A space's folder is named by the space id, which data-analyst, the only
    writer, gives as a number; an upload without a space was filed under the
    name of the person's own folder."""
    return len(rel.parts) > 1 and rel.parts[0].isdigit()


def link_legacy_files(root: Path, space: str, file_ids: Iterable[Any]) -> Dict[str, int]:
    """Link each of ``file_ids`` stored outside every space's folder into
    ``space``'s folder, at the same place below it, with the files derived from
    it (``{id}.mp4.wav``). Counts the ids linked, already present in the space,
    and found nowhere outside a space's folder."""
    root = Path(root)
    wanted = {fid for fid in map(_stored_id, file_ids or []) if fid}
    counts = {"linked": 0, "present": 0, "missing": 0}
    if not wanted:
        return counts

    present: set[str] = set()
    legacy: Dict[str, List[Path]] = defaultdict(list)
    for path in root.rglob("*") if root.is_dir() else []:
        fid = path.name[:_UUID_LEN]
        if fid not in wanted or not path.is_file():
            continue
        rel = path.relative_to(root)
        if len(rel.parts) > 1 and rel.parts[0] == space:
            present.add(fid)
        elif not _in_a_space_folder(rel):
            legacy[fid].append(rel)

    for fid in wanted:
        if fid in present:
            counts["present"] += 1
        elif fid in legacy:
            for rel in legacy[fid]:
                dest = root / space / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(root / rel, dest)
                except OSError:
                    shutil.copy2(root / rel, dest)
            counts["linked"] += 1
        else:
            counts["missing"] += 1
    return counts


def claim_legacy_knowledge_bases(conn: Any, space: str, connection_ids: Iterable[Any]) -> List[int]:
    """Record ``space`` on the knowledge bases without one that were made for
    ``connection_ids`` (the space's connections). Returns their ids."""
    ids = sorted({str(c).strip() for c in connection_ids or [] if str(c or "").strip()})
    if not ids:
        return []
    rows = conn.execute(
        text(
            "UPDATE document_knowledge_bases SET space_id = :space, updated_at = CURRENT_TIMESTAMP "
            "WHERE COALESCE(space_id, '') = '' AND connection_id IN :ids RETURNING id"
        ).bindparams(bindparam("ids", expanding=True)),
        {"space": space, "ids": ids},
    ).fetchall()
    return sorted(row[0] for row in rows)
