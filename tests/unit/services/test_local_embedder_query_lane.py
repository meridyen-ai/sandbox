"""Sandbox local embedder: questions are memoised and run on the query lane;
an ingestion pass waits while a query runs."""
import threading
import time

from sandbox.services import local_embedder as le


class _Session:
    def __init__(self):
        self.runs = []

    def run(self, outputs, feed):
        import numpy as np
        self.runs.append(feed["input_ids"].shape[0])
        time.sleep(0.05)
        return [np.ones((feed["input_ids"].shape[0], 4), dtype=np.float32)]


class _Tok:
    def encode(self, text):
        class E:
            ids = [1, 2, 3]
            attention_mask = [1, 1, 1]
        return E()


def _fake_model():
    m = object.__new__(le._OnnxEmbedder)
    m._tok, m._sess, m._out, m._inputs = _Tok(), _Session(), "o", {"input_ids", "attention_mask"}
    m._run_lock, m._lane, m._queries = threading.Lock(), threading.Condition(), 0
    return m


def test_query_is_memoised_on_normalised_text(monkeypatch):
    m = _fake_model()
    monkeypatch.setattr(le, "_get_model", lambda: m)
    le._QUERY_MEMO.clear()
    assert le.embed_query("izin  süresi\n") == le.embed_query("izin süresi")
    assert m._sess.runs == [1]


def test_ingestion_pass_waits_for_a_running_query(monkeypatch):
    m = _fake_model()
    with m._lane:
        m._queries = 1
    done = threading.Event()
    t = threading.Thread(target=lambda: (m.encode(["a", "b"]), done.set()))
    t.start()
    time.sleep(0.1)
    assert not done.is_set()
    with m._lane:
        m._queries = 0
        m._lane.notify_all()
    t.join(5)
    assert done.is_set()


def test_query_does_not_wait_for_the_ingestion_lock():
    m = _fake_model()
    with m._run_lock:  # an ingestion pass holds the lock
        start = time.monotonic()
        m.encode(["q"], query=True)
        assert time.monotonic() - start < 1.0


def test_session_options_follow_the_environment():
    import types

    class Options(types.SimpleNamespace):
        def __init__(self):
            super().__init__(config={})

        def add_session_config_entry(self, key, value):
            self.config[key] = value

    ort = types.SimpleNamespace(
        SessionOptions=Options,
        ExecutionMode=types.SimpleNamespace(ORT_SEQUENTIAL="sequential"),
        GraphOptimizationLevel=types.SimpleNamespace(ORT_ENABLE_ALL="all"))
    opts = le.session_options(ort)
    assert opts.intra_op_num_threads == le.THREADS and opts.inter_op_num_threads == 1
    assert opts.execution_mode == "sequential" and opts.graph_optimization_level == "all"
    assert opts.enable_cpu_mem_arena is False and opts.enable_mem_pattern is False
    assert opts.config["session.intra_op.allow_spinning"] == ("1" if le.SPINNING else "0")
