"""Opt-in paging for the list routes, in one place. R-080.

Six routes returned a whole collection with no ceiling: `GET /api/jobs`,
`GET /api/threads`, `GET /api/kb/sources`, `GET /api/uploads`,
`GET /api/plots`, and the message list inside `GET /api/threads/{id}/state`.
Of those, `/api/jobs` is the one that matters, because every open tab polls
it on an interval and it walks a directory that only grows: measured at 5.5 ms
median with 8 jobs and 20.9 ms with 58, near enough linear, which is about
100 ms per poll at a few hundred jobs.

**Paging is opt-in, and that is the design decision rather than an
oversight.** A truncating default would have been silently wrong here. This
project's testing discipline rests on a two-sided cleanup diff: snapshot every
job, thread, plot and project before a run, snapshot again after, and delete
only the difference. Every script in `tests/backend`, the e2e suite and the
snapshot tooling read the full list. A default limit would not have failed any
of them; it would have made all of them quietly incomplete, which is the worse
outcome. So a request with no `limit` returns everything, exactly as before,
and only a caller that asks for a page gets one.

The response shape differs between the two on purpose. Without `limit` the
route returns the plain array it always returned, so no existing consumer
changes at all. With `limit` it returns an object carrying the page and the
total, because a page is useless without knowing how many there are, and a
caller that asked for a page has been written for that shape.
"""
from __future__ import annotations

from typing import Any, Optional

#: No caller gets to ask for an unbounded "page". Matches
#: `_CHILDREN_PAGE_LIMIT_MAX` in server/routes/jobs.py, which had the same
#: reasoning first.
LIST_PAGE_LIMIT_MAX = 500


def paged(rows: list, offset: int = 0, limit: Optional[int] = None) -> Any:
    """`rows` unchanged when no limit was asked for, otherwise one page of it.

    Returns either the list itself or
    ``{"rows": [...], "total": n, "offset": k, "limit": l}``.
    """
    if limit is None:
        return rows
    limit = max(1, min(int(limit), LIST_PAGE_LIMIT_MAX))
    offset = max(0, int(offset))
    return {
        "rows": rows[offset:offset + limit],
        "total": len(rows),
        "offset": offset,
        "limit": limit,
    }


def tail_window(rows: list, limit: Optional[int] = None) -> tuple[list, int]:
    """The LAST `limit` items, plus the true total.

    A conversation is read from its end, so windowing its message list from
    the front would hand back the opening exchange and hide the answer that
    just arrived. Returns `(rows, total)` unchanged when no limit is given.
    """
    total = len(rows)
    if limit is None:
        return rows, total
    limit = max(1, min(int(limit), LIST_PAGE_LIMIT_MAX))
    return rows[-limit:], total
