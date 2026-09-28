"""Local CPU text embedding for document knowledge bases (ONNX, no API key).

Same model the Call Center KB and the Data Analyst backend use
(perplexity-ai/pplx-embed-v1-0.6b, 1024-dim), run through onnxruntime. Document
indexing used to embed through OpenAI, which made every upload fail on a sandbox
without an OPENAI_API_KEY and sent document text off the box — the opposite of
what an air-gapped sandbox is for.

IMPORTANT: query and stored vectors MUST come from this same model. The query
vector is produced by the Data Analyst backend (services/local_embedder.py), so
the ONNX file and the output read here (`pooler_output`) mirror that module.
Vectors from different models are not comparable — mixing them returns nonsense
neighbours rather than an error.
"""

from __future__ import annotations

import os
import threading
from typing import Any, List, Optional

import structlog
from llama_index.core.embeddings import BaseEmbedding

logger = structlog.get_logger(__name__)

MODEL_NAME = os.getenv("LOCAL_EMBEDDING_MODEL", "perplexity-ai/pplx-embed-v1-0.6b")
EMBEDDING_DIMENSIONS = int(os.getenv("LOCAL_EMBEDDING_DIMS", "1024"))
ONNX_FILE = os.getenv("LOCAL_EMBEDDING_ONNX_FILE", "onnx/model.onnx")
#: Baked into the image at build time (see Dockerfile) so an air-gapped sandbox
#: never reaches for the network; a missing file falls back to a hub download.
MODEL_CACHE = os.getenv("LOCAL_EMBEDDING_CACHE", "/opt/embedding_models")
#: Chunks are ~300 tokens; the cap only guards against a pathological element
#: slipping through the splitter (attention cost grows with the square of it).
MAX_TOKENS = int(os.getenv("LOCAL_EMBEDDING_MAX_TOKENS", "2048"))
#: Chunks per forward pass. ONE, measured on real KB chunks (avg 265 tokens, max
#: 706) with 8 threads:
#:     batch 16   0.24 chunks/s   5.3GB peak   <- OOM-killed an 8GB sandbox
#:     batch  4   0.30 chunks/s   3.9GB
#:     batch  1   0.77 chunks/s   2.5GB
#: A batch is padded to its longest member, so digit-heavy chunks (one token per
#: digit) make every short neighbour pay full attention cost for nothing.
BATCH_SIZE = int(os.getenv("LOCAL_EMBEDDING_BATCH_SIZE", "1"))
#: Texts LlamaIndex hands over per call — bookkeeping only, not a forward pass.
LLAMAINDEX_BATCH_SIZE = 32

_model: Optional["_OnnxEmbedder"] = None
_lock = threading.Lock()


class _OnnxEmbedder:
    """tokenizers + onnxruntime only. Reads the graph's pooled sentence vector
    and L2-normalises it so cosine == dot product (matches pgvector `<=>`)."""

    def __init__(self, repo_id: str) -> None:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        def _get(name: str, optional: bool = False) -> Optional[str]:
            # Cache first, with no network attempt: the baked image resolves
            # here and an air-gapped box must not stall on a DNS timeout.
            try:
                return hf_hub_download(repo_id, name, cache_dir=MODEL_CACHE, local_files_only=True)
            except Exception:
                pass
            try:
                return hf_hub_download(repo_id, name, cache_dir=MODEL_CACHE)
            except Exception:
                if optional:
                    return None
                raise

        model_path = _get(ONNX_FILE)
        # External-weight sidecars (>2GB graphs are split); onnxruntime loads
        # them by name at session init, so they must sit beside the graph.
        for suffix in ("_data", "_data_1", "_data_2"):
            _get(ONNX_FILE + suffix, optional=True)

        self._tok = Tokenizer.from_file(_get("tokenizer.json"))
        self._tok.enable_truncation(max_length=MAX_TOKENS)

        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        # Input shapes change with every chunk. The arena keeps the high-water
        # mark of each shape it has seen and never returns it, so resident memory
        # only ratchets up over a long indexing run.
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False
        opts.intra_op_num_threads = int(os.getenv("LOCAL_EMBEDDING_THREADS", "8"))
        self._sess = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
        names = {o.name for o in self._sess.get_outputs()}
        self._out = "pooler_output" if "pooler_output" in names else self._sess.get_outputs()[0].name
        self._inputs = {i.name for i in self._sess.get_inputs()}
        # One forward pass at a time: the session already spreads a pass over
        # intra_op threads, so concurrent passes only fight for the same cores.
        self._run_lock = threading.Lock()

    def encode(self, texts: List[str]) -> List[List[float]]:
        import numpy as np

        enc = [self._tok.encode(t or " ") for t in texts]
        width = max(len(e.ids) for e in enc)
        ids = np.array([e.ids + [0] * (width - len(e.ids)) for e in enc], dtype=np.int64)
        mask = np.array(
            [e.attention_mask + [0] * (width - len(e.attention_mask)) for e in enc], dtype=np.int64
        )
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        with self._run_lock:
            out = self._sess.run([self._out], feed)[0]
        if out.ndim == 3:  # last_hidden_state → mean-pool over real tokens
            m = mask[..., None].astype(out.dtype)
            out = (out * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
        out = out / np.clip(np.linalg.norm(out, axis=1, keepdims=True), 1e-12, None)
        return out.astype(np.float32).tolist()


def _get_model() -> _OnnxEmbedder:
    """Load once. A load failure raises — and is retried on the next document —
    rather than silently indexing with some other model."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = _OnnxEmbedder(MODEL_NAME)
                logger.info("local_embedder_loaded", model=MODEL_NAME, dims=EMBEDDING_DIMENSIONS)
    return _model


def embed_texts(texts: List[str]) -> List[List[float]]:
    model = _get_model()
    out: List[List[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        out.extend(model.encode(texts[i:i + BATCH_SIZE]))
    return out


class LocalEmbedding(BaseEmbedding):
    """LlamaIndex adapter, so VectorStoreIndex chunks/embeds/stores as before."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("model_name", MODEL_NAME)
        kwargs.setdefault("embed_batch_size", LLAMAINDEX_BATCH_SIZE)
        super().__init__(**kwargs)

    @classmethod
    def class_name(cls) -> str:
        return "LocalEmbedding"

    def _get_text_embedding(self, text: str) -> List[float]:
        return embed_texts([text])[0]

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return embed_texts(texts)

    def _get_query_embedding(self, query: str) -> List[float]:
        return embed_texts([query])[0]

    async def _aget_text_embedding(self, text: str) -> List[float]:
        return self._get_text_embedding(text)

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return self._get_query_embedding(query)
