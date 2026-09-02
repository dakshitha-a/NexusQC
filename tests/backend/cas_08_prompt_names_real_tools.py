#!/usr/bin/env python3
"""Every tool the system prompt tells the model to call actually exists.

Found while rebuilding the active-space engine, and broader than it first
looked. `app/agent/prompts.py` instructed the model to call
`search_active_space_literature` and `explain_active_space` by name; neither is
in `STATIC_TOOLS`, because both are dispatched by the single `active_space`
wrapper (the prompt-budget pattern this codebase uses, see
docs/MODEL_CONTEXT_BUDGET.md). Chasing that turned up three more in the same
paragraph: `search_knowledge_base(doc_type=...)`, `search_academic_literature`
and `web_search` are all names of an older tool API, replaced by one `search`
tool taking `source='manuals'|'papers'|'scholar'|'web'`.

None of this raises. The model is told to call a tool that is not bound, tries
something, and the turn degrades quietly -- which is exactly the failure mode
that lets a stale prompt sit unnoticed for as long as this one did.

The check is deliberately shaped to be maintainable rather than exhaustive.
It looks for identifiers written in the prompt as a call, `name(`, which is how
the prompt names a tool it wants invoked, and requires each to be either a
registered tool or listed below as a known non-tool. Prose that merely mentions
a concept is not written that way and is not flagged.

Needs no pyscf and no live stack.

Run:  PYTHONPATH=$PWD python3 tests/backend/cas_08_prompt_names_real_tools.py
"""
import re
from pathlib import Path

from app.agent import prompts
from app.agent.tools import STATIC_TOOLS, get_executable_tools

PASS = 0
FAIL = 0

# Identifiers that appear in call form in the prompt but are not tools: python
# builtins, string methods, and the app's own vocabulary. Anything added here
# should be genuinely not-a-tool, not a tool someone forgot to register.
NOT_TOOLS = {
    "format", "join", "strip", "append", "replace", "lower", "upper", "split",
    "range", "print", "round", "enumerate",
}


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f"\n         {detail}" if detail else ""))


def main() -> int:
    registered = {t.name for t in STATIC_TOOLS}
    executable = {t.name for t in get_executable_tools()}
    src = Path(prompts.__file__).read_text()

    print(f"{len(registered)} tools are offered to the model: "
          f"{', '.join(sorted(registered))}")

    called = {m for m in re.findall(r"\b([a-z][a-z0-9_]{3,})\(", src)}
    suspects = sorted(c for c in called
                      if c not in registered and c not in NOT_TOOLS
                      and "_" in c)

    print("\nEvery name the prompt writes as a call is a tool the model has")
    check(f"no unregistered tool names in prompts.py "
          f"(candidates checked: {len(called)})",
          not suspects,
          f"named in the prompt but not bound: {suspects}. Either register "
          f"them, rewrite the prompt to name the tool that does the job, or "
          f"add a genuine non-tool to NOT_TOOLS in this script.")

    print("\nThe specific names this script was written for stay gone")
    for stale in ("search_active_space_literature", "explain_active_space",
                  "search_knowledge_base", "search_academic_literature",
                  "web_search"):
        check(f"prompts.py does not tell the model to call {stale}()",
              f"{stale}(" not in src,
              f"{stale}( still appears; it is not in STATIC_TOOLS")

    print("\nand the tools that replaced them are the ones named")
    check("the prompt points at active_space for active-space work",
          "active_space tool" in src or "active_space(" in src)
    check("the prompt points at search(source=...) for lookups",
          "search(source=" in src)

    print("\nThe wrappers really do cover what the retired names did")
    check("active_space is registered", "active_space" in registered)
    check("search is registered", "search" in registered)
    check("every registered tool is also executable",
          registered <= executable,
          f"offered but not executable: {sorted(registered - executable)}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
