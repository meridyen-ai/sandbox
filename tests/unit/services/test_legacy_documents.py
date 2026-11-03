"""Aydın Group (space 18) opened "AI SOFYA_Arge - v2.docx" in a Data chat on
2026-11-01 and got {"detail":"File not found"}. It was uploaded on 2026-07-24,
before a document call named its space: the file was stored at the top of the
store (``/app/data/documents/e28c3421-….docx``) and its knowledge base
recorded no space. Since a document call reads only inside its space's folder,
that file, 2,343 more of July–August and 17 knowledge bases answered no one.

The backend, which knows which space owns each connection and file, claims
them for their space: the files are linked into the space's folder and the
knowledge bases made for its connections take its id. Nothing inside another
space's folder, and no knowledge base that already has a space, is claimed.
"""
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from sandbox.services import rest_api
from sandbox.services.legacy_documents import (
    claim_legacy_knowledge_bases,
    link_legacy_files,
)

DOCX = "e28c3421-daea-428e-b0dc-4b6e9ff7cd7e"
PDF = "0b7f2a51-6a8e-4c4f-9a43-0d7c1f2e9b10"
MAIL = "5d0c3a77-2f1b-4b8e-8f6a-3c9d2e1a7b44"


def _store(root: Path, rel: str, data: bytes = b"bytes") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_a_file_stored_before_spaces_is_read_for_its_space_once_claimed(tmp_path, monkeypatch):
    monkeypatch.setattr(rest_api, "_DOCUMENTS_DIR", tmp_path)
    _store(tmp_path, f"{DOCX}.docx", b"AI SOFYA")
    assert rest_api._stored_documents(DOCX, "18") == []  # the reported 404

    assert link_legacy_files(tmp_path, "18", [DOCX]) == {"linked": 1, "present": 0, "missing": 0}

    found = rest_api._stored_documents(DOCX, "18")
    assert found == [tmp_path / "18" / f"{DOCX}.docx"]
    assert found[0].read_bytes() == b"AI SOFYA"
    assert rest_api._stored_documents(DOCX, "25") == []


def test_a_folder_upload_without_a_space_keeps_its_folder(tmp_path):
    _store(tmp_path, f"cv_pdf/{PDF}.pdf")
    link_legacy_files(tmp_path, "23", [PDF])
    assert (tmp_path / "23" / "cv_pdf" / f"{PDF}.pdf").is_file()


def test_derived_files_come_along(tmp_path):
    _store(tmp_path, f"{PDF}.mp4")
    _store(tmp_path, f"{PDF}.mp4.wav")
    link_legacy_files(tmp_path, "4", [PDF])
    assert sorted(p.name for p in (tmp_path / "4").iterdir()) == [f"{PDF}.mp4", f"{PDF}.mp4.wav"]


def test_another_spaces_file_is_never_claimed(tmp_path):
    _store(tmp_path, f"25/{MAIL}.txt")
    _store(tmp_path, f"25/Inbox/{PDF}.pdf")
    assert link_legacy_files(tmp_path, "18", [MAIL, PDF]) == {"linked": 0, "present": 0, "missing": 2}
    assert not (tmp_path / "18").exists()


def test_a_legacy_file_two_spaces_use_is_claimed_by_both(tmp_path):
    original = _store(tmp_path, f"{PDF}.pdf")
    link_legacy_files(tmp_path, "23", [PDF])
    link_legacy_files(tmp_path, "4", [PDF])
    assert (tmp_path / "23" / f"{PDF}.pdf").is_file()
    assert (tmp_path / "4" / f"{PDF}.pdf").is_file()
    assert original.is_file()


def test_claiming_again_changes_nothing(tmp_path):
    _store(tmp_path, f"{DOCX}.docx")
    link_legacy_files(tmp_path, "18", [DOCX])
    assert link_legacy_files(tmp_path, "18", [DOCX]) == {"linked": 0, "present": 1, "missing": 0}
    assert [p.name for p in (tmp_path / "18").iterdir()] == [f"{DOCX}.docx"]


@pytest.mark.parametrize("bad", ["*", f"../{DOCX}", "12", "", None, DOCX.upper(), f"{DOCX}/x"])
def test_only_stored_file_ids_are_claimed(tmp_path, bad):
    _store(tmp_path, f"{DOCX}.docx")
    _store(tmp_path, "12ab.txt")
    assert link_legacy_files(tmp_path, "18", [bad])["linked"] == 0
    assert not (tmp_path / "18").exists()


@pytest.fixture
def kb_db():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE document_knowledge_bases ("
            "id INTEGER PRIMARY KEY, space_id TEXT, connection_id TEXT, updated_at TIMESTAMP)"
        ))
        conn.execute(text(
            "INSERT INTO document_knowledge_bases (id, space_id, connection_id) VALUES "
            "(1, '', '6'), (13, NULL, '22'), (7, '', '13'), (21, '4', '38'), (22, '44', '6')"
        ))
    return engine


def _spaces(engine):
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT id, space_id FROM document_knowledge_bases")).fetchall())


def test_knowledge_bases_made_for_the_spaces_connections_take_its_id(kb_db):
    with kb_db.begin() as conn:
        assert claim_legacy_knowledge_bases(conn, "18", ["6", "22"]) == [1, 13]
    spaces = _spaces(kb_db)
    assert spaces[1] == "18" and spaces[13] == "18"
    assert spaces[22] == "44"  # same connection id, already owned: untouched
    assert spaces[7] == ""  # another connection's


def test_a_knowledge_base_that_has_a_space_keeps_it(kb_db):
    with kb_db.begin() as conn:
        assert claim_legacy_knowledge_bases(conn, "5", ["38", "13"]) == [7]
        assert claim_legacy_knowledge_bases(conn, "23", ["13"]) == []
    spaces = _spaces(kb_db)
    assert spaces[21] == "4" and spaces[7] == "5"


def test_no_connections_claim_nothing(kb_db):
    with kb_db.begin() as conn:
        assert claim_legacy_knowledge_bases(conn, "18", []) == []
    assert _spaces(kb_db)[1] == ""
