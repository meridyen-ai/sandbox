"""Data Scientist bug chat r004/r006 (2026-10-30, TP Türkiye): a document source
answers, yet the source picker says "Failed" for its .pptx/.docx.

Live evidence: every document indexed since 2026-10-29 10:06 ended
``status='failed'`` with
    [ONNXRuntimeError] ... External data path escapes model directory.
    External data path: "model.onnx_data" resolved path:
    "/opt/embedding_models/blobs/a8/a8d2…" allowed directory: "/opt/embedding_models/blobs/e4"

The embedding model is baked as a Hugging Face cache (huggingface_hub 2.x):
``snapshots/<rev>/onnx/model.onnx`` and ``model.onnx_data`` are symlinks to
blobs in DIFFERENT shard directories. onnxruntime 1.31 resolves both links and
refuses an external-data file whose real location is not beside the graph's
real location — so the sandbox could not load the model at all, and every
document's vectors (and every question's) failed.

This builds a tiny model in that exact layout and loads it through the real
loader (``_OnnxEmbedder``) — no network, no Postgres.

Run inside the sandbox image:
    python -m pytest tests/unit/services/test_data_scientist_r006_embedder_hub_layout.py
"""
import json
import os

import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
ort = pytest.importorskip("onnxruntime")

from onnx import TensorProto, helper, numpy_helper  # noqa: E402

from sandbox.services import local_embedder as le  # noqa: E402

REPO = "meridyen-test/tiny-embed"
VOCAB = {"[PAD]": 0, "[UNK]": 1, "izin": 2, "süresi": 3, "rapor": 4}
DIM = 8


def _tiny_model(dirpath: str) -> None:
    """input_ids/attention_mask -> Gather(embedding, external) -> mean -> pooler_output."""
    emb = np.arange(len(VOCAB) * DIM, dtype=np.float32).reshape(len(VOCAB), DIM) + 1.0
    w = numpy_helper.from_array(emb, name="embed_tokens.weight")
    ids = helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["b", "t"])
    mask = helper.make_tensor_value_info("attention_mask", TensorProto.INT64, ["b", "t"])
    out = helper.make_tensor_value_info("pooler_output", TensorProto.FLOAT, ["b", DIM])
    nodes = [
        helper.make_node("Gather", ["embed_tokens.weight", "input_ids"], ["h"], axis=0),
        helper.make_node("ReduceMean", ["h"], ["pooler_output"], axes=[1], keepdims=0),
    ]
    graph = helper.make_graph(nodes, "tiny", [ids, mask], [out], [w])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 9
    onnx.save_model(
        model, os.path.join(dirpath, "model.onnx"), save_as_external_data=True,
        all_tensors_to_one_file=True, location="model.onnx_data", size_threshold=0,
    )


def _tokenizer_json() -> str:
    return json.dumps({
        "version": "1.0", "truncation": None, "padding": None, "added_tokens": [],
        "normalizer": None, "pre_tokenizer": {"type": "Whitespace"},
        "post_processor": None, "decoder": None,
        "model": {"type": "WordLevel", "vocab": VOCAB, "unk_token": "[UNK]"},
    })


def _hub_cache(root) -> str:
    """The layout the sandbox image has: snapshot files are symlinks into blobs
    sharded by the first two hex digits — graph and weights in different shards."""
    cache = root / "embedding_models"
    build = root / "build"
    build.mkdir()
    _tiny_model(str(build))
    (build / "tokenizer.json").write_text(_tokenizer_json())
    repo_dir = cache / ("models--" + REPO.replace("/", "--"))
    snap = repo_dir / "snapshots" / "2c4d510d"
    (snap / "onnx").mkdir(parents=True)
    (repo_dir / "refs").mkdir()
    (repo_dir / "refs" / "main").write_text("2c4d510d")
    for name, shard, digest in (
        ("onnx/model.onnx", "e4", "e42d63025a44"),
        ("onnx/model.onnx_data", "a8", "a8d2446f2332"),
        ("tokenizer.json", "a4", "a415a74fa7d9"),
    ):
        blob = cache / "blobs" / shard / digest
        blob.parent.mkdir(parents=True, exist_ok=True)
        os.replace(build / os.path.basename(name), blob)
        link = snap / name
        os.symlink(os.path.relpath(blob, link.parent), link)
    return str(cache)


@pytest.fixture
def hub_cache(tmp_path, monkeypatch):
    cache = _hub_cache(tmp_path)
    monkeypatch.setattr(le, "MODEL_CACHE", cache)
    monkeypatch.setattr(le, "STAGE_DIR", str(tmp_path / "stage"))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    return cache


def test_data_scientist_r006_layout_is_the_one_onnxruntime_refuses(hub_cache):
    """Guard on the fixture itself: a plain path load of this layout is what
    failed in production (if onnxruntime ever stops refusing it, this says so)."""
    snap = os.path.join(hub_cache, "models--meridyen-test--tiny-embed", "snapshots", "2c4d510d", "onnx")
    with pytest.raises(Exception, match="External data path"):
        ort.InferenceSession(os.path.join(snap, "model.onnx"), providers=["CPUExecutionProvider"])


def test_data_scientist_r006_embedder_loads_from_a_sharded_hub_cache(hub_cache):
    model = le._OnnxEmbedder(REPO)  # raised "External data path escapes model directory"
    vecs = model.encode(["izin süresi", "rapor"])
    assert len(vecs) == 2 and len(vecs[0]) == DIM
    for v in vecs:
        assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5
    assert vecs[0] != vecs[1]
    # The question lane uses the same session (one text each: the tiny graph
    # does not mask padding, so compare unpadded passes).
    assert model.encode(["rapor"], query=True)[0] == pytest.approx(model.encode(["rapor"])[0])


def test_data_scientist_r006_weights_are_staged_once_as_real_files(hub_cache, tmp_path):
    le._OnnxEmbedder(REPO)
    staged = list((tmp_path / "stage").glob("*/*"))
    names = sorted(p.name for p in staged)
    assert names == ["model.onnx", "model.onnx_data"]
    assert all(p.is_file() and not p.is_symlink() for p in staged)
    before = {p.name: p.stat().st_mtime_ns for p in staged}
    le._OnnxEmbedder(REPO)  # a second start reuses them
    assert {p.name: p.stat().st_mtime_ns for p in (tmp_path / "stage").glob("*/*")} == before


def test_data_scientist_r006_nowhere_to_write_still_loads(hub_cache, monkeypatch):
    def refuse(*_a, **_k):
        raise PermissionError("read-only")

    monkeypatch.setattr(le, "_stage_side_by_side", refuse)
    model = le._OnnxEmbedder(REPO)
    assert len(model._weights) == 1  # the weights were handed over in memory
    assert len(model.encode(["izin süresi"])[0]) == DIM
