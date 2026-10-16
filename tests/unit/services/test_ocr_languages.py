"""OCR language choice per document (services/ocr_languages.py)."""

from __future__ import annotations

import pytest

from sandbox.services import ocr_languages as O

ALL = frozenset({"eng", "tur", "ara", "deu", "fra", "spa", "rus"})
TR_TEXT = (
    "Kadın çalışanların gece postalarında çalıştırılma koşulları hakkında yönetmelik. "
    "İşveren, gece postalarında çalıştıracağı kadın çalışanların sağlık raporlarını almakla yükümlüdür."
)
AR_TEXT = "تلتزم الشركة بحماية البيانات الشخصية للموظفين وفقا للقانون المعمول به في جميع الفروع والإدارات"
EN_TEXT = "The employer shall provide transport for employees working night shifts between the hours stated."


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("DOCUMENT_OCR_LANGUAGES", "DOCUMENT_OCR_FALLBACK_LANGUAGES", "DOCUMENT_OCR_DETECT"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("value,code", [
    ("tr", "tur"), ("TR-tr", "tur"), ("tr_TR", "tur"), ("turkish", "tur"), ("tur", "tur"),
    ("ar", "ara"), ("en", "eng"), ("zh-cn", "chi_sim"), ("", None), ("12", None), (None, None), (5, None),
])
def test_to_tesseract_code(value, code):
    assert O.to_tesseract_code(value) == code


def test_parse_languages_keeps_order_and_drops_unknown():
    assert O.parse_languages("eng+tur, ar;xx1") == ["eng", "tur", "ara"]


def test_detected_language_first_then_english():
    chosen = O.choose(probe=lambda installed: TR_TEXT, installed=ALL)
    assert chosen.codes == ("tur", "eng") and chosen.source == "detected"


def test_probe_is_given_the_installed_languages():
    seen = []
    O.choose(probe=lambda installed: seen.append(installed) or EN_TEXT, installed=ALL)
    assert seen == [ALL]


@pytest.mark.parametrize("script,code", [
    ("Latin", "eng"), ("Arabic", "ara"), ("Cyrillic", "rus"), (None, "eng"), ("Klingon", "eng"),
    ("Greek", "eng"),  # ell not installed: English
])
def test_probe_language_follows_the_script(script, code):
    assert O.probe_languages_for(script, ALL) == code


def test_probe_reads_the_page_in_its_script(monkeypatch):
    calls = []

    def fake(binary, args, timeout):
        calls.append(args)
        return "Page number: 0\nScript: Arabic\nScript confidence: 4.2\n" if "--psm" in args else AR_TEXT

    monkeypatch.setattr(O, "_tesseract", fake)
    monkeypatch.setattr(O, "_all_packs", lambda: ALL | {"osd"})
    assert O._probe_image("tesseract", "/p.png", ALL, 5) == AR_TEXT
    assert calls[1][-2:] == ["-l", "ara"]


def test_english_document_stays_english_only():
    assert O.choose(probe=lambda installed: EN_TEXT, installed=ALL).codes == ("eng",)


def test_hint_is_added_after_the_detected_language():
    chosen = O.choose(hint="tr", probe=lambda installed: AR_TEXT, installed=ALL)
    assert chosen.codes == ("ara", "tur", "eng") and chosen.source == "detected+hint"


def test_hint_alone_when_nothing_can_be_detected():
    chosen = O.choose(hint="tr", probe=lambda installed: "12 / 3", installed=ALL)
    assert chosen.codes == ("tur", "eng") and chosen.source == "hint"


def test_fallback_when_nothing_is_known():
    chosen = O.choose(probe=lambda installed: "", installed=ALL)
    assert chosen.tesseract == O.DEFAULT_FALLBACK and chosen.source == "fallback"


def test_probe_failure_is_not_a_failure():
    def boom(installed):
        raise RuntimeError("tesseract crashed")

    assert O.choose(hint="ar", probe=boom, installed=ALL).codes == ("ara", "eng")


def test_env_forces_languages(monkeypatch):
    monkeypatch.setenv("DOCUMENT_OCR_LANGUAGES", "tur+eng")
    chosen = O.choose(hint="ar", probe=lambda installed: AR_TEXT, installed=ALL)
    assert chosen.codes == ("tur", "eng") and chosen.source == "env"


def test_detection_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("DOCUMENT_OCR_DETECT", "0")
    called = []
    chosen = O.choose(probe=lambda installed: called.append(1) or TR_TEXT, installed=ALL)
    assert not called and chosen.source == "fallback"


def test_only_installed_languages_are_used(monkeypatch):
    monkeypatch.setenv("DOCUMENT_OCR_FALLBACK_LANGUAGES", "eng+tur+ara")
    installed = frozenset({"eng"})
    assert O.choose(hint="tr", probe=lambda installed: TR_TEXT, installed=installed).codes == ("eng",)
    assert O.fallback_languages(installed) == ("eng",)


def test_unusable_env_setting_falls_back_to_auto(monkeypatch):
    monkeypatch.setenv("DOCUMENT_OCR_LANGUAGES", "xxx1")
    assert O.choose(probe=lambda installed: TR_TEXT, installed=ALL).codes == ("tur", "eng")


def test_non_ocr_file_types_are_not_probed(monkeypatch):
    monkeypatch.setattr(O, "_all_packs", lambda: ALL)
    monkeypatch.setattr(O, "probe_text", lambda *a: pytest.fail("probed a docx"))
    assert O.for_document("/x.docx", "docx", hint="tr").codes == ("tur", "eng")


def test_extracted_text_is_put_in_composed_form():
    """Decomposed Turkish letters (as OCR can emit them) are stored composed,
    so the lexical index and queries match; superscripts are left alone."""
    import unicodedata

    from sandbox.services.rest_api import _normalize_arabic_presentation_forms as normalize

    decomposed = unicodedata.normalize("NFD", "İşçi güvenliği ÖĞÜ ışık")
    assert decomposed != "İşçi güvenliği ÖĞÜ ışık"
    assert normalize(decomposed) == "İşçi güvenliği ÖĞÜ ışık"
    assert normalize("x² H₂O ﬁle") == "x² H₂O ﬁle"
    assert normalize("ﻋﻤﺮﻭ") == "عمرو"
