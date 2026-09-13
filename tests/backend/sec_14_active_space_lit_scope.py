#!/usr/bin/env python3
"""The active-space literature search sees only the caller's own papers.
Regression test for R-009.

    PYTHONPATH=$PWD python3 tests/backend/sec_14_active_space_lit_scope.py

R-009. `active_space_lit.search` builds its default knowledge-base backend as

    lambda q: search_knowledge_base.func(q, doc_type="paper", k=5, state=None)

and `app/rag/query_tool.py` reads the owner to scope the search off exactly
that `state`. With it None the search is unfiltered, so user A asking for an
active space retrieved user B's private uploaded paper verbatim into A's
conversation and into the resulting job's `literature_notes`. query_tool's own
comment had already named the harm and singled out `doc_type="paper"` as the
more privacy-sensitive of its two cases: an uploaded paper can be genuinely
proprietary.

Nothing had to be invented to fix it. Both tools that call this
(`search_active_space_literature` and `explain_active_space`) already receive
`state: Annotated[AgentState, InjectedState]`; the argument was simply never
threaded through, because this signature was written to take injectable
backends for testing and the production default was written to fit it.

**What this script tests, and why that is the right target.** The scoping
itself lives in `query_tool.py` and is not in question; it works, and its
`owner_user_id` filter is what the ownership retrofit built. The defect was
one missing argument between the tool and the backend. So this checks the
wiring: that a state handed to `search` reaches the knowledge-base call, that
both call sites pass one, and that omitting it now raises instead of quietly
searching everyone's papers. A silent unscoped default is the specific thing
that made this invisible for as long as it was, so "the caller forgot" must
not be a quieter road to a cross-user read than "the caller asked for it".

Runs entirely in process: no server, no database, no network.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import check, summary  # noqa: E402

print("R-009: the paper search is scoped to whoever asked\n")

from app.agent import active_space_lit  # noqa: E402
from app.rag import query_tool  # noqa: E402

print("1. the state handed to search reaches the knowledge-base backend")
seen: list[dict] = []


class _Recorder:
    """Stands in for the search_knowledge_base StructuredTool, which the
    backend reaches through its `.func` attribute."""

    @staticmethod
    def func(query, doc_type=None, k=None, state=None):
        seen.append({"query": query, "doc_type": doc_type, "state": state})
        return "No matching passages found in the knowledge base."


real_kb = query_tool.search_knowledge_base
query_tool.search_knowledge_base = _Recorder
try:
    caller_state = {"owner_user_id": "user-a-uuid"}
    findings = None
    try:
        findings = active_space_lit.search(
            "uracil", n_states=3, basis="cc-pvdz", state=caller_state,
            scholar=lambda q: "no results",
        )
    except TypeError as exc:
        # This is what the finding looks like from here before the fix: the
        # function has no way to be told who is asking, so the default
        # backend passes state=None and the paper search is unscoped.
        check("search() accepts the caller's state at all", False, "", f"TypeError: {exc}")
        active_space_lit.search("uracil", n_states=3, basis="cc-pvdz",
                                scholar=lambda q: "no results")
    check("the knowledge-base tier ran at all", bool(seen), f"{len(seen)} call(s)")
    check("every knowledge-base call carried the caller's state",
          bool(seen) and all(c["state"] is caller_state for c in seen),
          f"{len(seen)} call(s), states {[c['state'] for c in seen]}")
    check("and asked for papers, which is the scoped, privacy-sensitive case",
          bool(seen) and all(c["doc_type"] == "paper" for c in seen),
          f"doc_types {[c['doc_type'] for c in seen]}")
    check("the search still returns findings", findings is not None,
          f"matched_at={getattr(findings, 'matched_at', None)!r}")

    print("\n2. omitting the state is refused, not silently unscoped")
    try:
        active_space_lit.search("uracil", n_states=3, basis="cc-pvdz",
                                scholar=lambda q: "no results")
        check("search() with no state and no kb backend raises", False, "",
              "it built an unscoped paper search instead")
    except ValueError as exc:
        check("search() with no state and no kb backend raises", True,
              f"ValueError: {str(exc)[:60]}...")

    print("\n3. a test may still inject its own backend without a state")
    seen.clear()
    active_space_lit.search("uracil", kb=lambda q: "nothing", scholar=lambda q: "nothing")
    check("an explicit kb backend needs no state", not seen,
          "the default backend was never built")
finally:
    query_tool.search_knowledge_base = real_kb

print("\n4. both call sites pass one")
from app.agent import tools as agent_tools  # noqa: E402

for fn in ("search_active_space_literature", "explain_active_space"):
    src = inspect.getsource(getattr(agent_tools, fn).func)
    calls = [ln.strip() for ln in src.splitlines() if "active_space_lit.search(" in ln]
    check(f"{fn} calls active_space_lit.search with state=",
          bool(calls) and all("state=state" in c for c in calls),
          f"{calls}")

print("\n5. and no other caller of the knowledge base passes state=None")
offenders = []
for path in sorted((REPO / "app").rglob("*.py")):
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if "search_knowledge_base.func" in line and "state=None" in line:
            offenders.append(f"{path.relative_to(REPO)}:{i}")
check("no search_knowledge_base.func call site passes state=None",
      not offenders, "", "; ".join(offenders))

summary()
