#!/usr/bin/env python3
"""The active-space tools count correctly, report a dead backend as nothing,
and can be called the way the prompt says.
Regression test for R-015, R-016, R-035, R-084 and R-086, and for R-014's
sibling in the troubleshoot prompt (R-041, R-042).

    PYTHONPATH=$PWD python3 tests/backend/cas_11_literature_and_counts.py

R-015. `_call` returned "<source> search failed (...)" when a backend raised,
and `_is_empty` matched the three tools' own "nothing found" strings and not
that one. So a backend that THREW was absorbed as a literature hit: the
recommendation read as grounded in a paper, `matched_at` named a tier, on the
strength of a stack trace. The empty result is this feature's guardrail --
the user kept the literature step for exactly that reason -- so an exception
reading as a hit removes the thing the step is for.

R-016. `explain_active_space` computed its configuration count as
`n_alpha = n_beta = active_electrons // 2`, which is only right for a closed
shell: an odd electron count silently lost one, and a triplet was counted as
a singlet. CAS(7,6) came out as 400 against the true 300 and a triplet
CAS(6,6) as 400 against 225 -- and the number is used to tell the user
whether their space can support the states they asked for, so overcounting
is the dangerous direction.

R-035. The system prompt says not to ask for a basis before an active-space
search; the tool schema required one. The model could only ask anyway or
invent one, and an invented basis narrows the literature search to conditions
nobody asked for.

R-084: a bucketing branch tested the task name twice where its own comment
said it tested the subtype. R-086: the scholar response body was parsed
outside the try that was supposed to make any failure degrade gracefully.
"""
from __future__ import annotations

import inspect
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import check, summary  # noqa: E402

print("R-015: a backend that raises found nothing\n")
from app.agent import active_space_lit as lit  # noqa: E402

raised = lit._call(lambda q: (_ for _ in ()).throw(RuntimeError("boom")), "knowledge base", "q")
check("a raising backend's answer reads as empty", lit._is_empty(raised), f"{raised[:60]}...",
      "it is absorbed as a literature hit, so a recommendation is reported as "
      "grounded in a paper on the strength of a stack trace")
check("and a genuine 'nothing found' still reads as empty",
      lit._is_empty("No matching passages found in the knowledge base."), "")
check("while a real hit does not",
      not lit._is_empty("Smith et al. used CAS(10,9) for uracil."), "")

print("\nR-016: the configuration count knows about spin")
from app.agent import tools as agent_tools  # noqa: E402


class _FakeState(dict):
    pass


def count_for(ne: int, no: int, multiplicity: int) -> int | None:
    """Drive explain_active_space and read the number back out of its text."""
    import re
    state = {"molecule": {"name": "probe", "identifier": "probe", "symbols": ["C"],
                          "coords": [[0.0, 0.0, 0.0]], "charge": 0,
                          "multiplicity": multiplicity}}
    try:
        out = agent_tools.explain_active_space.func(
            active_electrons=ne, active_orbitals=no, n_excited_states=None,
            basis=None, state=state)
    except Exception as exc:                                    # noqa: BLE001
        return f"raised: {type(exc).__name__}"
    if not isinstance(out, str) or out.startswith("raised:"):
        return None
    m = re.search(r"holds at most ([\d,]+)", out)
    return int(m.group(1).replace(",", "")) if m else None


def truth(ne: int, no: int, multiplicity: int) -> int:
    two_s = max(0, multiplicity - 1)
    na = (ne + two_s) // 2
    return math.comb(no, na) * math.comb(no, ne - na)


for ne, no, mult in ((4, 4, 1), (6, 6, 1), (5, 5, 2), (7, 6, 2), (6, 6, 3)):
    want = truth(ne, no, mult)
    got = count_for(ne, no, mult)
    naive = math.comb(no, ne // 2) ** 2
    detail = f"got {got}, correct {want}" + (f", the closed-shell formula gives {naive}"
                                             if naive != want else "")
    check(f"CAS({ne},{no}) at multiplicity {mult} holds {want} configurations",
          got == want, detail)

print("\nR-035: the active-space tool can be called the way the prompt says")
for name in ("active_space", "search_active_space_literature"):
    schema = getattr(agent_tools, name).args_schema.model_json_schema()
    required = schema.get("required") or []
    check(f"{name} does not require a basis", "basis" not in required, f"required={required}",
          "the prompt says not to ask for one, so the model must either ask "
          "anyway or invent one")

print("\nR-084: the cas_reco notice branch tests the subtype")
from app.agent import job_watcher  # noqa: E402

wsrc = inspect.getsource(job_watcher.JobWatcher._poll_once)
check("the second clause reads the subtype, not the task again",
      'spec.get("subtype") in _CAS_RECO_NOTICE_SUBTYPES' in wsrc, "",
      'it still reads spec.get("task") == "cas_reco" twice, so it tests nothing')
from app.chemistry.registry2.tasks import TASKS  # noqa: E402

registry_subtypes = {s for (t, s) in TASKS if t == "cas_reco"}
allow = getattr(job_watcher, "_CAS_RECO_NOTICE_SUBTYPES", None)
check("and the allow-list matches what the registry actually defines",
      allow is not None and set(allow) == registry_subtypes,
      f"{sorted(allow) if allow else None} vs {sorted(registry_subtypes)}",
      "there is no allow-list, so nothing narrows the branch to the subtypes "
      "that actually produce a recommendation")

print("\nR-086: a non-JSON 200 from the scholar API degrades")
from app.agent import scholar_search  # noqa: E402

ssrc = inspect.getsource(scholar_search)
i = ssrc.index("resp.json()")
window = ssrc[max(0, i - 300):i]
check("resp.json() is inside a try", "try:" in window, "",
      "a 200 carrying an HTML error page raises JSONDecodeError straight out "
      "of the tool, where the docstring promises 'use web_search instead'")

print("\nR-014, R-041, R-042: the troubleshooting message")
from app.agent import troubleshoot  # noqa: E402
from app.agent.tools import STATIC_TOOLS  # noqa: E402

tsrc = inspect.getsource(troubleshoot)
bound = {t.name for t in STATIC_TOOLS}
named = {n for n in ("search_knowledge_base", "web_search", "search_academic_literature",
                     "search", "start_job_draft", "submit_draft") if f"{n}(" in tsrc}
check("every tool the message names is actually bound", named <= bound,
      f"names {sorted(named)}", f"names {sorted(named - bound)}, which are not bound")
check("it describes the job by what it was, not by its level of theory",
      'task = spec.get("task")' in tsrc and "at the {method} level" in tsrc, "",
      "it reads spec['method'] and calls that the job type, so a failed "
      "optimisation is described to the model as 'a dft job'")
arch = (REPO / "docs" / "ARCHITECTURE.md").read_text()
check("R-041: the architecture no longer claims a troubleshooting budget",
      "code-enforced budget" not in arch, "",
      "the cap belonged to the auto-retry loop that was removed")

summary()
