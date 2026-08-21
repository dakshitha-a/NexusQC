"""Job ids whose terminal result the agent has already told the user about.

Every finished job was being summarized twice. The agent polls
check_job_status until the job completes and reports the results in its own
turn; then JobWatcher notices the same transition and starts a second,
synthetic turn whose notice says "check their status and give the user a
concise summary" -- so the model dutifully re-checks and says it again. Four
jobs in one real conversation each got two full summaries, back to back,
several hundred words apart.

The signal that separates the two cases is simply whether the agent has
already read a TERMINAL status for that job. A job it polled while still
running has not been reported and still needs the notice; a job whose
completed result it has already seen has been. So check_job_status records
the ids it returned a finished result for, and the watcher skips those in
its plain "summarize this" bucket.

Deliberately only that bucket. The Wigner and active-space branches do
something the agent has NOT already done -- render a spectrum, open a
pre-filled draft -- so they still fire even if the results were reported in
the turn that submitted them.

In memory, not on disk, and that is the right trade: a restart between the
report and the watcher's tick costs one duplicated summary, which is
exactly today's behaviour, while persisting it would mean a durable store
whose only job is suppressing a paragraph.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_reported: set[str] = set()
# Bounded so a long-lived process cannot accumulate ids indefinitely. Far
# larger than any plausible number of jobs in flight between a report and
# the watcher tick that follows it, which is the only window that matters.
_MAX_TRACKED = 4096


def mark_reported(job_id: str) -> None:
    """Record that the agent has seen and relayed this job's final result."""
    if not job_id:
        return
    with _lock:
        if len(_reported) >= _MAX_TRACKED:
            _reported.clear()
        _reported.add(job_id)


def was_reported(job_id: str) -> bool:
    with _lock:
        return job_id in _reported


def forget(job_id: str) -> None:
    """Drop an id -- for tests, and for a job whose results are deleted."""
    with _lock:
        _reported.discard(job_id)
