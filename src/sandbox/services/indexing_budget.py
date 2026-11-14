"""A document's embedding ends when nobody can use its result.

The caller of ``/documents/process`` waits a bounded time for the answer (the
Data Analyst backend: ``SANDBOX_PROCESS_TIMEOUT``, 5400 s) and reports the
document as failed after that. The embedding itself had no bound: it ran on
the local CPU model for as long as the file needed, on every embedding thread,
with nobody left to read the result. A 12 MB text file held the sandbox's cores
for hours and needed days.

``EmbeddingWatch`` is called after every embedding pass of one document (see
``local_embedder.after_each_pass``) and ends the job, by raising, when:

* the job has used its time budget (``TooLargeToIndex``);
* a short sample shows it cannot finish anywhere near the budget
  (``TooLargeToIndex``, after a minute or two instead of after the budget);
* the document is no longer being indexed, because it was deleted or marked
  failed meanwhile (``IndexingStopped``).

It also writes the progress of the embedding step, which is how it learns the
third case: the progress writer reports whether the document still wants it.
"""

from __future__ import annotations

import os
import time
from typing import Callable

#: Seconds one document may take from the start of its job (parsing, OCR and
#: transcription included). Keep it equal to what the caller waits for.
BUDGET_SECONDS = float(os.getenv("DOCUMENT_INDEX_BUDGET_SECONDS", "5400"))
#: A job is ended early only when its projected duration is beyond the budget
#: by this factor: speed on a shared host moves, and a file near the limit
#: should get its chance and be ended by the limit itself.
EARLY_STOP_FACTOR = 1.5
#: Passes measured before a projection is trusted.
MIN_SAMPLE = 20
#: Seconds between progress writes (each one is a database round trip).
CHECK_EVERY = 10.0


class TooLargeToIndex(Exception):
    """The file cannot be embedded inside the time budget. ``str()`` of it is
    shown to the person who uploaded the file."""


class IndexingStopped(Exception):
    """The document was deleted, or is no longer marked as being processed."""


def _duration(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes == 1:
        return "1 minute"
    if minutes < 120:
        return f"{minutes} minutes"
    return f"{round(seconds / 3600)} hours"


def _too_large(needed: float | None, budget: float) -> TooLargeToIndex:
    advice = "Split it into smaller files and upload them one by one."
    if needed is None:
        return TooLargeToIndex(
            f"This file took longer to index than the limit of {_duration(budget)}. {advice}"
        )
    return TooLargeToIndex(
        f"This file is too large to index: it would take about {_duration(needed)}, "
        f"and the limit is {_duration(budget)}. {advice}"
    )


class EmbeddingWatch:
    """Call with the number of passages just embedded, after every pass.

    ``job_started`` is the ``clock()`` reading at the start of the document's
    job. ``report(done, total)`` writes the progress and returns False when
    the document is no longer being indexed.
    """

    def __init__(
        self,
        total: int,
        job_started: float,
        report: Callable[[int, int], bool],
        *,
        budget: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._total = total
        self._job_started = job_started
        self._report = report
        self._budget = BUDGET_SECONDS if budget is None else budget
        self._clock = clock
        self._done = 0
        self._last_report: float | None = None
        # The first pass loads the model; speed is measured from its end.
        self._first: tuple[float, int] | None = None

    def _projected(self, now: float) -> float | None:
        """Seconds the whole job would take at the measured speed, or None
        while too little has been measured."""
        if self._first is None:
            return None
        first_at, first_done = self._first
        measured = self._done - first_done
        if measured < MIN_SAMPLE:
            return None
        per_passage = (now - first_at) / measured
        return (now - self._job_started) + per_passage * (self._total - self._done)

    def __call__(self, passages: int = 1) -> None:
        self._done += passages
        now = self._clock()
        if self._first is None:
            self._first = (now, self._done)
        finished = self._done >= self._total

        if finished or self._last_report is None or now - self._last_report >= CHECK_EVERY:
            self._last_report = now
            if not self._report(min(self._done, self._total), self._total):
                raise IndexingStopped("the document is no longer being indexed")
        if finished:
            return  # the work is done: store it, whatever the clock says

        projected = self._projected(now)
        if now - self._job_started >= self._budget:
            raise _too_large(projected, self._budget)
        if projected is not None and projected > self._budget * EARLY_STOP_FACTOR:
            raise _too_large(projected, self._budget)
