"""Vector chunking: today's sizes by default, section-aware cuts on request."""
from sandbox.services import chunking as ch

LAW = (
    "İŞ KANUNU\nBİRİNCİ BÖLÜM\nGenel Hükümler\nAmaç ve kapsam\n"
    "Madde 1 - Bu Kanunun amacı işverenler ile işçilerin haklarını düzenlemektir. "
    + "Bu Kanun bütün işyerlerine uygulanır. " * 8 + "\n\n"
    "Tanımlar\nMadde 2 - Bir iş sözleşmesine dayanarak çalışan gerçek kişiye işçi denir. "
    + "İşçi çalıştıran gerçek veya tüzel kişiye işveren denir. " * 10 + "\n\n"
    "Madde 3 - Kısa madde.\n"
)


def test_defaults_are_today(monkeypatch):
    for k in ("DOCUMENT_CHUNKER", "DOCUMENT_CHUNK_CHARS", "DOCUMENT_CHUNK_OVERLAP", "DOCUMENT_CHUNK_MIN_CHARS"):
        monkeypatch.delenv(k, raising=False)
    assert ch.index_tag() == 0 and ch.table_suffix() == ""
    assert ch.unstructured_kwargs() == {"max_characters": 1000, "new_after_n_chars": 900,
                                        "combine_text_under_n_chars": 500, "overlap": 100}
    monkeypatch.setenv("DOCUMENT_CHUNK_CHARS", "600")
    assert ch.table_suffix().startswith("_c") and ch.unstructured_kwargs()["max_characters"] == 600


def test_articles_start_chunks_and_sentences_stay_whole(monkeypatch):
    monkeypatch.setenv("DOCUMENT_CHUNKER", "sections")
    monkeypatch.setenv("DOCUMENT_CHUNK_CHARS", "400")
    monkeypatch.setenv("DOCUMENT_CHUNK_MIN_CHARS", "0")
    paras = [{"text": line} for line in LAW.split("\n") if line.strip()]
    groups = ch.group_blocks(paras, ch.settings())
    texts = ["\n".join(b["text"] for b in g) for g in groups]
    assert any(t.startswith("Madde 2") for t in texts) and any(t.startswith("Madde 3") for t in texts)
    assert all(len(t) <= 400 + 1 for t in texts)
    # a block longer than the target is cut between sentences
    for g in groups:
        for b in g:
            assert b["text"].rstrip().endswith(".") or len(b["text"]) < 80


def test_long_block_keeps_its_metadata_and_page_breaks_hold(monkeypatch):
    monkeypatch.setenv("DOCUMENT_CHUNKER", "sections")
    monkeypatch.setenv("DOCUMENT_CHUNK_CHARS", "300")
    blocks = [{"text": "Uzun bir cümle burada yer alır. " * 30, "page_num": 1, "bbox": [0, 0, 1, 1]},
              {"text": "Sayfa iki.", "page_num": 2, "bbox": [0, 0, 1, 1]}]
    groups = ch.group_blocks(blocks, ch.settings(), flush_on=lambda a, b: a["page_num"] != b["page_num"])
    assert all(b["bbox"] == [0, 0, 1, 1] for g in groups for b in g)
    assert groups[-1][0]["text"] == "Sayfa iki." and all(len(g) >= 1 for g in groups)


def test_split_text_today_and_sections(monkeypatch):
    text = "\n\n".join(f"Paragraf {i}. " + "Kelime cümlesi. " * 20 for i in range(10))
    monkeypatch.delenv("DOCUMENT_CHUNKER", raising=False)
    monkeypatch.delenv("DOCUMENT_CHUNK_CHARS", raising=False)
    today = ch.split_text(text)
    assert all(len(c) <= 1000 for c in today) and len(today) >= 3
    monkeypatch.setenv("DOCUMENT_CHUNKER", "sections")
    monkeypatch.setenv("DOCUMENT_CHUNK_CHARS", "500")
    assert all(len(c) <= 500 + 2 for c in ch.split_text(text))
