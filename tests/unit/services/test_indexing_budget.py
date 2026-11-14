"""A document's embedding ends when nobody can use its result.

No model and no database: the clock is a counter the test moves, and the
progress writer is a recorder. Pins:
  * a file that fits is embedded to the end and its progress is written;
  * a file that cannot finish inside the caller's wait is stopped after a short
    sample, with a message a person can act on;
  * a file a little over the limit is not stopped on a guess, only at the limit;
  * a slow first pass (the model loading) does not count as the file's speed;
  * a document deleted while it is embedded is stopped at the next progress
    write, and progress is written at most once per interval;
  * the embedder calls the hook of its own thread after every pass, and an
    exception from the hook ends the embedding.
"""
from __future__ import annotations

import threading

import pytest

from sandbox.services import indexing_budget as ib
from sandbox.services import local_embedder as le


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Progress:
    """Stands in for the document row: records writes, says if it still exists."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, int]] = []
        self.wanted = True

    def __call__(self, done: int, total: int) -> bool:
        self.writes.append((done, total))
        return self.wanted


def _embed(watch, clock, total, seconds_per_pass, first_pass=None):
    """Run passes until the watch stops the job. Returns the passes done."""
    for i in range(total):
        clock.now += first_pass if (i == 0 and first_pass is not None) else seconds_per_pass
        watch(1)
    return total


def test_a_file_that_fits_is_embedded_to_the_end():
    clock, progress = _Clock(), _Progress()
    watch = ib.EmbeddingWatch(400, clock(), progress, budget=5400, clock=clock)
    assert _embed(watch, clock, 400, 7.5) == 400  # 50 minutes
    assert progress.writes[-1] == (400, 400)
    dones = [d for d, _ in progress.writes]
    assert dones == sorted(dones)


def test_a_file_that_cannot_finish_is_stopped_after_a_short_sample():
    clock, progress = _Clock(), _Progress()
    watch = ib.EmbeddingWatch(20799, clock(), progress, budget=5400, clock=clock)
    done = 0
    with pytest.raises(ib.TooLargeToIndex) as stopped:
        for done in range(1, 20800):
            clock.now += 7.5
            watch(1)
    assert done <= ib.MIN_SAMPLE + 2
    message = str(stopped.value)
    assert "43 hours" in message and "90 minutes" in message
    assert "Traceback" not in message and "\n" not in message


def test_a_file_a_little_over_the_limit_runs_until_the_limit():
    clock, progress = _Clock(), _Progress()
    # 880 passes of 7.5 s = 110 minutes: over 90, under the early-stop margin.
    watch = ib.EmbeddingWatch(880, clock(), progress, budget=5400, clock=clock)
    done = 0
    with pytest.raises(ib.TooLargeToIndex):
        for done in range(1, 881):
            clock.now += 7.5
            watch(1)
    assert done == 720  # 5400 s / 7.5 s


def test_time_before_embedding_counts_against_the_limit():
    clock, progress = _Clock(), _Progress()
    job_started = clock()
    clock.now += 4800  # 80 minutes of transcription before the first pass
    watch = ib.EmbeddingWatch(400, job_started, progress, budget=5400, clock=clock)
    with pytest.raises(ib.TooLargeToIndex):
        _embed(watch, clock, 400, 7.5)  # 50 more minutes


def test_a_slow_first_pass_is_not_the_files_speed():
    clock, progress = _Clock(), _Progress()
    watch = ib.EmbeddingWatch(3000, clock(), progress, budget=5400, clock=clock)
    # The model loads during the first pass (4 minutes); the rest take 1 s.
    assert _embed(watch, clock, 3000, 1.0, first_pass=240.0) == 3000


def test_a_deleted_document_is_stopped_at_the_next_progress_write():
    clock, progress = _Clock(), _Progress()
    watch = ib.EmbeddingWatch(1000, clock(), progress, budget=5400, clock=clock)
    for _ in range(30):
        clock.now += 1.0
        watch(1)
    progress.wanted = False
    with pytest.raises(ib.IndexingStopped):
        for _ in range(30):
            clock.now += 1.0
            watch(1)
    # 60 s of passes: about one write per CHECK_EVERY seconds, not one per pass.
    assert len(progress.writes) <= 60 / ib.CHECK_EVERY + 1


def test_the_limit_message_reads_as_a_sentence():
    clock, progress = _Clock(), _Progress()
    watch = ib.EmbeddingWatch(50, clock(), progress, budget=60, clock=clock)
    with pytest.raises(ib.TooLargeToIndex) as stopped:
        _embed(watch, clock, 50, 31.0)  # the limit passes before a sample exists
    assert str(stopped.value).startswith(
        "This file took longer to index than the limit of 1 minute. "
    )


def test_the_last_pass_is_never_stopped():
    clock, progress = _Clock(), _Progress()
    watch = ib.EmbeddingWatch(3, clock(), progress, budget=10, clock=clock)
    clock.now += 4
    watch(1)
    clock.now += 4
    watch(1)
    clock.now += 4  # past the limit, but the work is done: keep it
    watch(1)
    assert progress.writes[-1] == (3, 3)


# ── the embedder's per-pass hook ─────────────────────────────────────────────


class _Model:
    def __init__(self) -> None:
        self.passes: list[int] = []

    def encode(self, texts, *, query=False):
        self.passes.append(len(texts))
        return [[0.0] for _ in texts]


def test_the_embedder_calls_the_hook_after_every_pass(monkeypatch):
    model = _Model()
    monkeypatch.setattr(le, "_get_model", lambda: model)
    monkeypatch.setattr(le, "BATCH_SIZE", 2)
    seen: list[int] = []
    with le.after_each_pass(seen.append):
        le.embed_texts(["a", "b", "c", "d", "e"])
    assert seen == [2, 2, 1]
    le.embed_texts(["f"])  # outside the block: no hook
    assert seen == [2, 2, 1]


def test_an_exception_from_the_hook_ends_the_embedding(monkeypatch):
    model = _Model()
    monkeypatch.setattr(le, "_get_model", lambda: model)
    monkeypatch.setattr(le, "BATCH_SIZE", 1)

    def stop(_n):
        raise ib.IndexingStopped("deleted")

    with pytest.raises(ib.IndexingStopped):
        with le.after_each_pass(stop):
            le.embed_texts(["a", "b", "c"])
    assert model.passes == [1]


def test_the_hook_belongs_to_its_own_thread(monkeypatch):
    model = _Model()
    monkeypatch.setattr(le, "_get_model", lambda: model)
    seen: list[int] = []
    with le.after_each_pass(seen.append):
        other = threading.Thread(target=lambda: le.embed_texts(["x", "y"]))
        other.start()
        other.join(5)
    assert seen == []
