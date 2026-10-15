"""How a document is cut into vector chunks: the same settings and rules as
the Data app's lexical passages (data-analyst src/backend/services/chunking.py),
so the two halves of a passage search see the same pieces of text.

  DOCUMENT_CHUNKER          sections (default) | windows (the earlier cut)
  DOCUMENT_CHUNK_CHARS      target size, characters (600)
  DOCUMENT_CHUNK_OVERLAP    overlap inside a section (vector chunks: 100)
  DOCUMENT_CHUNK_MIN_CHARS  a smaller section joins the next (default: 40% of the target)

The default is sections / 600 (the evaluation: recall@10 +3.0, MRR +3.9,
nDCG@10 +3.1 over the earlier windows / 1000). The earlier cut (``windows``,
1000): digital PDFs group PyMuPDF blocks up to
1000 characters (never across a page); scans and Office files go through
Unstructured's ``by_title`` chunker (max 1000, soft 900, combine under 500,
overlap 100); a re-transcribed text is packed by paragraphs up to 1000. The
LlamaIndex SentenceSplitter afterwards (1024 tokens) changes almost nothing.

``sections``: a heading ("Madde N", "Article N", numbered and Markdown
headings, parts and chapters, a short line in capitals) or a question line
("S:", "Q:") starts a new chunk; inside a section blocks are packed up to the
target, a block longer than the target is cut between sentences (never inside
one), and a smaller section joins the next while both fit. Unstructured gets
the same sizes.

``table_suffix()`` names the vector table of any settings but the earlier
windows / 1000 (``…_e<dim>_c<tag>``): a size change fills a table of its own,
side by side with the earlier one. Search reads both; a file re-indexed into
the new table leaves the earlier one, so each file is in exactly one.
"""
from __future__ import annotations

import os
import re
import zlib
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

WINDOWS, SECTIONS = "windows", "sections"
DEFAULT_MODE = SECTIONS
DEFAULT_CHARS = 600
DEFAULT_OVERLAP = 100


@dataclass(frozen=True)
class ChunkSettings:
    mode: str = DEFAULT_MODE
    chars: int = DEFAULT_CHARS
    overlap: int = DEFAULT_OVERLAP
    min_chars: Optional[int] = None

    @property
    def min_size(self) -> int:
        return self.min_chars if self.min_chars is not None else int(self.chars * 0.4)


def _env_int(name: str) -> Optional[int]:
    raw = (os.environ.get(name) or "").strip()
    try:
        return max(0, int(raw)) if raw else None
    except ValueError:
        return None


def settings() -> ChunkSettings:
    mode = (os.environ.get("DOCUMENT_CHUNKER") or DEFAULT_MODE).strip().lower()
    chars = max(200, _env_int("DOCUMENT_CHUNK_CHARS") or DEFAULT_CHARS)
    overlap = _env_int("DOCUMENT_CHUNK_OVERLAP")
    return ChunkSettings(mode=mode if mode in (WINDOWS, SECTIONS) else DEFAULT_MODE, chars=chars,
                         overlap=min(DEFAULT_OVERLAP if overlap is None else overlap, chars // 2),
                         min_chars=_env_int("DOCUMENT_CHUNK_MIN_CHARS"))


# The earlier cut, whose vectors live in the table without a suffix.
EARLIER = ChunkSettings(mode=WINDOWS, chars=1000, overlap=DEFAULT_OVERLAP)


def index_tag(s: Optional[ChunkSettings] = None) -> int:
    s = s or settings()
    if s == EARLIER:
        return 0
    return 1 + zlib.crc32(f"{s.mode}:{s.chars}:{s.overlap}:{s.min_chars}".encode()) % 999_999


def table_suffix(s: Optional[ChunkSettings] = None) -> str:
    tag = index_tag(s)
    return f"_c{tag}" if tag else ""


def unstructured_kwargs(s: Optional[ChunkSettings] = None) -> dict:
    """by_title sizes: today's numbers for the defaults."""
    s = s or settings()
    return {
        "max_characters": s.chars,
        "new_after_n_chars": int(s.chars * 0.9),
        "combine_text_under_n_chars": s.min_chars if s.min_chars is not None else (500 if s == EARLIER
                                                                                   else s.min_size),
        "overlap": s.overlap,
    }


# ── headings and sentences ──────────────────────────────────────────────────

def _fold(s: str) -> str:
    import unicodedata

    s = (s or "").replace("İ", "i").replace("I", "i").replace("ı", "i").lower()
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


_MD = re.compile(r"^#{1,6}\s+\S")
_NUMBERED = re.compile(r"^\d{1,3}(?:\.\d{1,3}){0,5}[.)]?\s+[^\W\d_]", re.UNICODE)
_ARTICLE = re.compile(r"^(?:ek\s+|gecici\s+|mukerrer\s+)?(?:madde|article|art\.)\s*\d+")
_LADDER = re.compile(r"^(?:[^\W\d_]+\s+)?(?:kitap|kisim|bolum|ayrim|book|part|chapter|title)(?:\s+[\dIVXLC]+)?\s*[.:]?$")
_QUESTION = re.compile(r"^(?:S|Q|Soru|SORU|Question|QUESTION)\s*:\s")
_SENTENCE = re.compile(r"[.!?…][\"”’)]*\d{0,3}\s+(?=[\"“‘(]?[^\W_\d]|\d)")


def is_heading(line: str) -> bool:
    s = (line or "").strip()
    if not s or len(s) > 140:
        return False
    if _MD.match(s) or _QUESTION.match(s):
        return True
    f = _fold(s)
    if _ARTICLE.match(f) or (len(s) <= 40 and _LADDER.match(f)):
        return True
    if _NUMBERED.match(s) and len(s) <= 100 and not s.endswith((".", ",", ";", ":")):
        return True
    letters = [c for c in s if c.isalpha()]
    return 8 <= len(s) <= 110 and len(letters) >= 6 and all(c.isupper() for c in letters) and len(s.split()) >= 2


def sentences(text: str) -> List[str]:
    out, pos = [], 0
    for m in _SENTENCE.finditer(text):
        out.append(text[pos:m.end()])
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    return [s for s in out if s.strip()]


def _cut_long(text: str, size: int) -> List[str]:
    """A text longer than ``size``: whole sentences packed up to it (a single
    longer sentence by words)."""
    out, cur = [], ""
    for sent in sentences(text):
        parts = [sent] if len(sent) <= size else [sent[i:i + size] for i in range(0, len(sent), size)]
        for part in parts:
            if cur and len(cur) + len(part) > size:
                out.append(cur)
                cur = part
            else:
                cur += part
    if cur.strip():
        out.append(cur)
    return out


# ── grouping blocks (PyMuPDF) and plain text ───────────────────────────────

def group_blocks(blocks: Sequence[dict], s: ChunkSettings,
                 flush_on: Callable[[dict, dict], bool] = lambda a, b: False) -> List[List[dict]]:
    """Blocks ({"text": …, …}) grouped into chunks: a heading block starts a
    new group, a group never exceeds the target, ``flush_on(prev, next)`` adds
    the caller's own breaks (a page change). A block longer than the target
    becomes several blocks of whole sentences, each keeping its metadata."""
    expanded: List[dict] = []
    for b in blocks:
        text = b.get("text") or ""
        if len(text) > s.chars:
            expanded.extend({**b, "text": piece} for piece in _cut_long(text, s.chars))
        else:
            expanded.append(b)
    groups: List[List[dict]] = []
    cur: List[dict] = []
    size = 0
    for b in expanded:
        text = b.get("text") or ""
        heading = is_heading(text.split("\n", 1)[0])
        starts_new = cur and (flush_on(cur[-1], b) or size + len(text) + 1 > s.chars
                              or (heading and size >= s.min_size))
        if starts_new:
            groups.append(cur)
            cur, size = [], 0
        cur.append(b)
        size += len(text) + 1
    if cur:
        groups.append(cur)
    return groups


def split_text(text: str, s: Optional[ChunkSettings] = None) -> List[str]:
    """A whole text (a re-transcription) as chunks, by paragraphs."""
    s = s or settings()
    paras = [{"text": p.strip()} for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    if s.mode == WINDOWS:
        out, cur = [], ""
        for p in paras:  # today's packing
            if cur and len(cur) + len(p["text"]) + 2 > s.chars:
                out.append(cur)
                cur = p["text"]
            else:
                cur = f"{cur}\n\n{p['text']}" if cur else p["text"]
        return out + ([cur] if cur else [])
    return ["\n\n".join(b["text"] for b in g) for g in group_blocks(paras, s)]
