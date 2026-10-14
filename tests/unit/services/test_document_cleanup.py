"""Deleting a knowledge-base document removes its vectors and stored files."""
from pathlib import Path

from sandbox.services.document_cleanup import remove_stored_files, vector_tables_for


def test_only_the_knowledge_bases_own_vector_tables():
    names = ["data_llamaindex_kb_1", "data_llamaindex_kb_1_e1024", "data_llamaindex_kb_12",
             "data_llamaindex_kb_12_e1024", "data_llamaindex_kb_1_e1024; DROP TABLE x", "document_kb_chunks"]
    assert vector_tables_for(1, names) == ["data_llamaindex_kb_1", "data_llamaindex_kb_1_e1024"]
    assert vector_tables_for("12", names) == ["data_llamaindex_kb_12", "data_llamaindex_kb_12_e1024"]


def test_stored_files_of_one_id_in_one_space(tmp_path: Path):
    space = tmp_path / "s1" / "Folder"
    space.mkdir(parents=True)
    (space / "abc-1.pdf").write_bytes(b"x")
    (space / "abc-1_page1.png").write_bytes(b"x")
    (space / "abc-2.pdf").write_bytes(b"x")
    other = tmp_path / "s2"
    other.mkdir()
    (other / "abc-1.pdf").write_bytes(b"x")
    assert remove_stored_files(tmp_path, "s1", "abc-1") == 2
    assert sorted(p.name for p in space.iterdir()) == ["abc-2.pdf"]
    assert (other / "abc-1.pdf").exists()


def test_ids_that_would_be_globs_remove_nothing(tmp_path: Path):
    (tmp_path / "s1").mkdir()
    (tmp_path / "s1" / "abc.pdf").write_bytes(b"x")
    for bad in ("*", "../s1/abc", "", None, "a/b"):
        assert remove_stored_files(tmp_path, "s1", bad) == 0
    assert remove_stored_files(tmp_path, None, "abc") == 0
    assert remove_stored_files(tmp_path, "missing", "abc") == 0
    assert (tmp_path / "s1" / "abc.pdf").exists()
