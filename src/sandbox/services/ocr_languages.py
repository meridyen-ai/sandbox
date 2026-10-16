"""Which Tesseract languages a document is OCRed in.

Tesseract reads only the scripts and letters of the languages it is told to
use: an English-only run turns Turkish "ş ğ ı İ" into "s g i I" (or drops the
word), and Arabic into Latin look-alikes. The image ships a set of language
packs (see the Dockerfile); this module picks, per document, which of them a
scan is read with:

1. ``DOCUMENT_OCR_LANGUAGES`` — when set to languages (``eng+tur``), every
   document uses exactly those. ``auto`` or unset: decided per document.
2. The languages detected in the document itself: Tesseract's script
   detection (OSD) reads the first page's script; the page is OCRed once with
   one language of that script (English for Latin: fast, and its letters are
   enough to tell Turkish from German) and the text's language is detected.
3. The language hint the caller sends (the organization's language), added
   after the detected one — so a Turkish organization's scans are always read
   with Turkish too, and an Arabic document in that organization still gets
   Arabic.
4. English is always added: most business documents carry some English.
5. Nothing detected and no hint: the fallback set
   (``DOCUMENT_OCR_FALLBACK_LANGUAGES``, default ``eng+tur+ara+deu+fra+spa+rus``).

Every choice is limited to the languages installed in this image, so a hint or
setting naming a missing pack is skipped instead of failing Tesseract.

Settings (environment):

- ``DOCUMENT_OCR_LANGUAGES``          ``auto`` (default) or e.g. ``eng+tur``
- ``DOCUMENT_OCR_FALLBACK_LANGUAGES`` the set used when nothing is known
- ``DOCUMENT_OCR_DETECT``             ``1`` (default) / ``0``: probe the scan
- ``DOCUMENT_OCR_PROBE_PAGES``        pages OCRed for the probe (default 2; it
                                      stops at the first page with enough text)
- ``DOCUMENT_OCR_PROBE_TIMEOUT``      seconds per probe page (default 60)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterable, Optional

from sandbox.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_FALLBACK = "eng+tur+ara+deu+fra+spa+rus"

# File types Tesseract reads directly (images) or through rendered pages (PDF).
IMAGE_TYPES = frozenset({"png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "webp"})
OCR_FILE_TYPES = IMAGE_TYPES | {"pdf"}

# ISO 639-1 codes and English names → Tesseract (ISO 639-2/T) codes. Only the
# languages a hint or a detector plausibly names; Tesseract codes themselves
# are accepted as they are.
_ISO_TO_TESSERACT = {
    "en": "eng", "tr": "tur", "ar": "ara", "de": "deu", "fr": "fra", "es": "spa",
    "ru": "rus", "it": "ita", "pt": "por", "nl": "nld", "pl": "pol", "fa": "fas",
    "az": "aze", "uk": "ukr", "el": "ell", "he": "heb", "ro": "ron", "bg": "bul",
    "cs": "ces", "sk": "slk", "hu": "hun", "sv": "swe", "da": "dan", "no": "nor",
    "fi": "fin", "hr": "hrv", "sr": "srp", "sl": "slv", "id": "ind", "ms": "msa",
    "vi": "vie", "th": "tha", "hi": "hin", "ur": "urd", "bn": "ben", "ja": "jpn",
    "ko": "kor", "zh-cn": "chi_sim", "zh-tw": "chi_tra", "zh": "chi_sim",
    "ka": "kat", "hy": "hye", "kk": "kaz", "uz": "uzb", "ku": "kmr",
}
_NAME_TO_ISO = {
    "english": "en", "turkish": "tr", "arabic": "ar", "german": "de", "french": "fr",
    "spanish": "es", "russian": "ru", "italian": "it", "portuguese": "pt",
    "dutch": "nl", "persian": "fa", "farsi": "fa", "azerbaijani": "az",
    "ukrainian": "uk", "greek": "el", "hebrew": "he",
}
_TESSERACT_CODE = re.compile(r"^[a-z]{3}(_[a-z]+)?$")

# How sure the detector must be of a language to read the scan with it.
_MIN_PROBABILITY = 0.2
# Letters the probe must have produced before its language is trusted.
_MIN_PROBE_LETTERS = 40
# A probe stops once it has this much text.
_ENOUGH_PROBE_CHARS = 1500


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(_env(name, str(default))))
    except ValueError:
        return default


def to_tesseract_code(value: object) -> Optional[str]:
    """``value`` as a Tesseract language code: ISO 639-1 (``tr``, ``tr-TR``),
    English names (``turkish``) and Tesseract codes (``tur``). None when it
    names no language."""
    if not isinstance(value, str):
        return None
    s = value.strip().lower().replace("_", "-")
    if not s or len(s) > 32:
        return None
    s = _NAME_TO_ISO.get(s, s)
    if s in _ISO_TO_TESSERACT:
        return _ISO_TO_TESSERACT[s]
    base = s.split("-")[0]
    if base in _ISO_TO_TESSERACT:
        return _ISO_TO_TESSERACT[base]
    raw = value.strip().lower()
    return raw if _TESSERACT_CODE.match(raw) else None


def parse_languages(value: str) -> list[str]:
    """``"eng+tur"`` / ``"eng, tur"`` / ``"en,tr"`` as Tesseract codes, in order."""
    out: list[str] = []
    for part in re.split(r"[+,;\s]+", value or ""):
        code = to_tesseract_code(part)
        if code and code not in out:
            out.append(code)
    return out


def _tesseract_binary() -> Optional[str]:
    return shutil.which(_env("TESSERACT_CMD", "tesseract"))


def installed_languages() -> frozenset[str]:
    """The language packs this Tesseract has (``osd`` excluded). Empty when
    Tesseract is missing or cannot be asked."""
    return _all_packs() - {"osd"}


def _available(codes: Iterable[str], installed: frozenset[str]) -> list[str]:
    out: list[str] = []
    for code in codes:
        if code and code not in out and (not installed or code in installed):
            out.append(code)
    return out


@dataclass(frozen=True)
class OcrLanguages:
    """The languages one document is OCRed in, and why."""

    codes: tuple[str, ...]
    source: str  # "env" | "detected" | "hint" | "detected+hint" | "fallback"
    detected: tuple[str, ...] = ()

    @property
    def tesseract(self) -> str:
        return "+".join(self.codes)


def fallback_languages(installed: Optional[frozenset[str]] = None) -> tuple[str, ...]:
    installed = installed_languages() if installed is None else installed
    codes = _available(parse_languages(_env("DOCUMENT_OCR_FALLBACK_LANGUAGES", DEFAULT_FALLBACK)), installed)
    if codes:
        return tuple(codes)
    # Nothing configured is installed: English when present, else whatever is.
    if not installed or "eng" in installed:
        return ("eng",)
    return tuple(sorted(installed))


def forced_languages(installed: Optional[frozenset[str]] = None) -> Optional[tuple[str, ...]]:
    """The languages DOCUMENT_OCR_LANGUAGES fixes for every document, if any."""
    value = _env("DOCUMENT_OCR_LANGUAGES", "auto")
    if not value or value.lower() == "auto":
        return None
    installed = installed_languages() if installed is None else installed
    codes = _available(parse_languages(value), installed)
    if not codes:
        logger.warning("ocr_languages_setting_unusable", value=value[:100],
                       installed=sorted(installed))
        return None
    return tuple(codes)


def detect_languages(text: str, *, limit: int = 2) -> list[str]:
    """Tesseract codes of the languages ``text`` is written in, most likely
    first; empty when there is too little text to tell."""
    letters = sum(1 for ch in text or "" if ch.isalpha())
    if letters < _MIN_PROBE_LETTERS:
        return []
    try:
        from langdetect import DetectorFactory, detect_langs
        from langdetect.lang_detect_exception import LangDetectException
    except ImportError:  # pragma: no cover — langdetect ships with unstructured
        logger.warning("langdetect_missing")
        return []
    DetectorFactory.seed = 0  # deterministic
    try:
        guesses = detect_langs(text[:20000])
    except LangDetectException:
        return []
    out: list[str] = []
    for guess in guesses:
        if guess.prob < _MIN_PROBABILITY:
            continue
        code = to_tesseract_code(guess.lang)
        if code and code not in out:
            out.append(code)
        if len(out) >= limit:
            break
    return out


def choose(
    *,
    hint: object = None,
    probe: Optional[Callable[[frozenset[str]], str]] = None,
    installed: Optional[frozenset[str]] = None,
) -> OcrLanguages:
    """The languages for one document.

    ``hint``: the caller's language (e.g. the organization's ``tr``).
    ``probe``: OCRs the start of the document (with languages from the
    installed set it is given) and returns the text; None skips detection.
    """
    installed = installed_languages() if installed is None else installed
    forced = forced_languages(installed)
    if forced:
        return OcrLanguages(codes=forced, source="env")

    fallback = fallback_languages(installed)
    hint_code = to_tesseract_code(hint)
    hinted = _available([hint_code] if hint_code else [], installed)

    detected: list[str] = []
    if probe is not None and _env("DOCUMENT_OCR_DETECT", "1") not in ("0", "false", "no", "off"):
        try:
            sample = probe(installed)
        except Exception as e:  # noqa: BLE001 — detection is an improvement, never a failure
            logger.warning("ocr_language_probe_failed", error=str(e))
            sample = ""
        detected = _available(detect_languages(sample), installed)

    if not detected and not hinted:
        return OcrLanguages(codes=fallback, source="fallback")
    codes = _available([*detected, *hinted, "eng"], installed)
    source = "detected+hint" if detected and hinted else ("detected" if detected else "hint")
    return OcrLanguages(codes=tuple(codes), source=source, detected=tuple(detected))


def without_probe(hint: object = None) -> OcrLanguages:
    """The languages when the document is not probed (no scan to read yet)."""
    return choose(hint=hint, probe=None)


# ── probing a document ───────────────────────────────────────────────────────

# Tesseract OSD script names → the language a probe reads that script with.
_SCRIPT_PROBE = {
    "Latin": "eng", "Arabic": "ara", "Cyrillic": "rus", "Greek": "ell", "Hebrew": "heb",
    "Han": "chi_sim", "HanS": "chi_sim", "HanT": "chi_tra", "Japanese": "jpn", "Korean": "kor",
    "Hangul": "kor", "Devanagari": "hin", "Thai": "tha", "Georgian": "kat", "Armenian": "hye",
}
_OSD_SCRIPT = re.compile(r"^Script:\s*(\S+)", re.MULTILINE)


def _tesseract(binary: str, args: list[str], timeout: int) -> str:
    # One thread: Tesseract's OpenMP threads slow it down badly on a busy host,
    # and a probe page is small. An operator's own setting wins.
    env = {**os.environ, "OMP_THREAD_LIMIT": os.environ.get("OMP_THREAD_LIMIT", "1")}
    try:
        out = subprocess.run([binary, *args], capture_output=True, timeout=timeout, check=False, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("ocr_probe_failed", error=str(e)[:300])
        return ""
    if out.returncode != 0:
        logger.info("ocr_probe_no_result", returncode=out.returncode,
                    error=(out.stderr or b"").decode("utf-8", "replace")[:300])
        return ""
    return (out.stdout or b"").decode("utf-8", "replace")


def probe_languages_for(script: Optional[str], installed: frozenset[str]) -> str:
    """The language a probe page is read with, from its OSD script."""
    code = _SCRIPT_PROBE.get(script or "", "eng")
    if installed and code not in installed:
        code = "eng" if "eng" in installed or not installed else sorted(installed)[0]
    return code


def _probe_image(binary: str, image: str, installed: frozenset[str], timeout: int) -> str:
    osd = _tesseract(binary, [image, "stdout", "--psm", "0"], timeout) if "osd" in _all_packs() else ""
    match = _OSD_SCRIPT.search(osd)
    return _tesseract(binary, [image, "stdout", "-l", probe_languages_for(match.group(1) if match else None,
                                                                          installed)], timeout)


@lru_cache(maxsize=1)
def _all_packs() -> frozenset[str]:
    """Every traineddata Tesseract lists (``osd`` included); cached."""
    binary = _tesseract_binary()
    if not binary:
        logger.warning("tesseract_not_found")
        return frozenset()
    # First line is the header ("List of available languages in ...").
    text = _tesseract(binary, ["--list-langs"], 15)
    return frozenset(ln.strip() for ln in text.splitlines()[1:] if ln.strip())


def probe_text(file_path: str, file_type: str, installed: frozenset[str]) -> str:
    """OCR text of the first page(s) of a scanned PDF or an image, read with
    one language of the page's script."""
    binary = _tesseract_binary()
    if not binary:
        return ""
    timeout = _env_int("DOCUMENT_OCR_PROBE_TIMEOUT", 60)
    ft = (file_type or "").lower()
    if ft in IMAGE_TYPES:
        return _probe_image(binary, file_path, installed, timeout)
    if ft != "pdf":
        return ""
    import fitz

    pages = _env_int("DOCUMENT_OCR_PROBE_PAGES", 2)
    parts: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ocr-probe-") as tmp:
        doc = fitz.open(file_path)
        try:
            for index in range(min(pages, len(doc))):
                image = os.path.join(tmp, f"p{index}.png")
                doc[index].get_pixmap(dpi=200).save(image)
                parts.append(_probe_image(binary, image, installed, timeout))
                if sum(len(p) for p in parts) >= _ENOUGH_PROBE_CHARS:
                    break
        finally:
            doc.close()
    return "\n".join(parts)


def for_document(file_path: str, file_type: str, *, hint: object = None) -> OcrLanguages:
    """The languages a scanned PDF or image is OCRed in (see the module doc)."""
    if (file_type or "").lower() not in OCR_FILE_TYPES:
        return without_probe(hint)
    chosen = choose(hint=hint, probe=lambda installed: probe_text(file_path, file_type, installed))
    logger.info("ocr_languages_chosen", languages=chosen.tesseract, source=chosen.source,
                detected=list(chosen.detected), hint=str(hint)[:16] if hint else None)
    return chosen
