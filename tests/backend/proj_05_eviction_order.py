#!/usr/bin/env python3
"""Quota eviction exhausts unarchived jobs before it touches an archive.

    PYTHONPATH=$PWD python3 tests/backend/proj_05_eviction_order.py

Archiving is deliberately NOT an exemption from the storage quota. A
category nothing can reclaim would let a user fill their quota with
un-evictable data and then be unable to submit anything at all, which is a
worse failure than losing the oldest of a set of finished results.

But it should not be nothing, either. Somebody who took the trouble to
name a project and file jobs into it has said something about what they
want to keep, and the ordering is where that gets respected: eviction
still runs oldest-first, with every unarchived job going before any
archived one, whatever the dates say.

The interesting case is precisely the one where age and archiving
disagree. So the archived job here is the OLDEST of the set: under the
previous plain created_at ordering it would have been the first thing
evicted, and it must now be the last.

Pure functions against a temporary registry and job tree. No stack, no
real jobs, nothing to clean up -- _evict_oldest_first's ordering is
decided entirely by the candidate dicts handed to it.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from app.auth import storage_quota  # noqa: E402

failures: list[str] = []
checks = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if not ok and detail else ""))
    if not ok:
        failures.append(label)


def _sink() -> dict:
    """The bucket dict _evict_oldest_first appends into, keyed the way
    _EVICTED_KEY spells it rather than by kind."""
    return {"evicted_jobs": [], "evicted_kb_sources": [], "evicted_uploads": [], "evicted_threads": []}


def candidate(key: str, created_at: float, archived: bool = False, size: int = 100) -> dict:
    return {"kind": "job", "key": key, "owner": "u1", "size": size,
            "created_at": created_at, "archived": archived}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="qatest_evict_"))
    evicted: list[str] = []
    # _evict does real disk work and cache invalidation; this test is about
    # the ORDER the chokepoint is reached in, so it is replaced with a
    # recorder. The real _evict is covered by the quota tests.
    real_evict = storage_quota._evict
    storage_quota._evict = lambda c: evicted.append(c["key"])
    try:
        print("\n== the archived job is the oldest, and still goes last ==")
        # 400 bytes of candidates against a 250-byte cap: exactly two must go,
        # which leaves the archived one and one unarchived one standing. A
        # cap that forces three would prove less: the archived job would
        # survive on count alone rather than on ordering.
        cands = [
            candidate("archived_oldest", created_at=1000.0, archived=True),
            candidate("plain_older", created_at=2000.0),
            candidate("plain_newer", created_at=3000.0),
            candidate("plain_newest", created_at=4000.0),
        ]
        total = storage_quota._evict_oldest_first(cands, 250, 400, _sink())
        check("exactly enough was evicted to get under the cap", total <= 250, f"total left {total}")
        check("the two oldest UNARCHIVED jobs went",
              evicted == ["plain_older", "plain_newer"], str(evicted))
        check("the archived job survived despite being the oldest of all",
              "archived_oldest" not in evicted,
              "under a plain created_at sort this is the first thing evicted, which is the regression")

        print("\n== but an archive is not exempt when nothing else is left ==")
        evicted.clear()
        cands = [
            candidate("archived_a", created_at=1000.0, archived=True),
            candidate("archived_b", created_at=2000.0, archived=True),
            candidate("plain", created_at=3000.0),
        ]
        total = storage_quota._evict_oldest_first(cands, 100, 300, _sink())
        check("the unarchived job goes first", evicted[0] == "plain", str(evicted))
        check("then the oldest archived one, rather than nothing at all",
              evicted[1] == "archived_a", str(evicted))
        check("and the quota is actually enforced", total <= 100, f"total left {total}")

        print("\n== other kinds sort as unarchived, so they go before an archive ==")
        evicted.clear()
        cands = [
            candidate("archived_job", created_at=1000.0, archived=True),
            # A KB source or a chat thread carries no "archived" key at all;
            # the sort has to read that as False rather than raising.
            {"kind": "kb", "key": "some_source", "owner": "u1", "size": 100, "created_at": 5000.0},
        ]
        total = storage_quota._evict_oldest_first(cands, 100, 200, _sink())
        check("a candidate with no archived key at all is handled",
              evicted == ["some_source"], str(evicted))
        check("so the project archive outlives a much newer knowledge-base source",
              "archived_job" not in evicted)

        print("\n== the flag reaches candidates from the real builder ==")
        # _job_candidates is what puts "archived" on a candidate in the
        # first place, so the ordering above is only meaningful if that
        # function really sets it. Checked by reading its source rather
        # than by building a job tree: the alternative is standing up
        # Postgres for one boolean.
        import inspect
        src = inspect.getsource(storage_quota._job_candidates)
        check("_job_candidates consults the project registry",
              "job_project_map" in src, "the ordering above would never see a True")
        check("and records it on each candidate", '"archived":' in src, src[-300:])
    finally:
        storage_quota._evict = real_evict
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{checks - len(failures)}/{checks} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
