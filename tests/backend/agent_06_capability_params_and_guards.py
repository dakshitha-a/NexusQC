#!/usr/bin/env python3
"""What the agent can discover, and what it does when there is nothing there.

Three things, all of them consequences of one reported conversation where a
job took several attempts to set up.

**A capability answer names the parameters a draft accepts.** Asked to seed
a CASSCF from a completed job's orbitals, the agent looked at the draft in
front of it, found no field for that, and told the user it would "check
whether this deployment supports that". `initial_orbitals_job_id` existed
the whole time. It then guessed the key name wrong and needed
`update_job_draft` to reject it before it learned the right one, because
the rejection message was the only place the names appeared. Making the
error path the sole documentation means being wrong once, in front of the
user, is a precondition for being right.

**An empty conversation does not reach the model.** A system prompt with
nothing after it is not a request Qwen's template will render, and Ollama
answers `500 no user query found in messages`. Reachable whenever a turn
runs against a conversation whose stored state is gone, the clearest case
being an approval card still open in a tab after its thread is deleted.

**Erasing a stopped turn's output says so.** The cleanup is correct and
stays, but it deletes messages, and a conversation it has touched shows a
tool result with no reply after it and no record of why.

Run:  PYTHONPATH=$PWD python3 tests/backend/agent_06_capability_params_and_guards.py
"""
from __future__ import annotations

import io
import logging
import sys

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.chemistry.registry2.lookup import capability_answer
from app.chemistry.registry2.params import params_for

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}" + (f" -- {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {label}\n         {detail}")


def capture(logger_name: str):
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.WARNING)
    lg = logging.getLogger(logger_name)
    lg.addHandler(handler)
    lg.setLevel(logging.WARNING)
    return buf, lg, handler


print("== a capability answer names the parameters a draft accepts ==")
answer = capability_answer("single_point", "ee", "casscf", "bagel")
params = answer.get("parameters") or []
names = [p["name"] for p in params]
check("the answer carries a parameter list", bool(params), f"{len(params)} parameter(s)")
check("including the one whose absence was reported as unsupported",
      "initial_orbitals_job_id" in names, ", ".join(names[:8]) + " ...")
check("and the active-space list the same conversation needed",
      "active_space_orbital_indices" in names)
check("it is the registry's own list, not a second copy",
      set(names) == {s.name for s in params_for("single_point", "ee")},
      f"{len(names)} vs {len(params_for('single_point', 'ee'))}")

seed = next((p for p in params if p["name"] == "initial_orbitals_job_id"), {})
check("each parameter says what it does", "what" in seed, str(seed)[:150])
check("the help text, not just the label -- the label alone omits the constraint",
      "SAME engine" in seed.get("what", ""), seed.get("what", "")[:120])
check("every parameter carries a type", all("type" in p for p in params))

# A task asked about without an engine, and without a method, must answer the
# same way -- those are the shapes a capability question actually arrives in.
for label, args in [("without an engine", ("single_point", "ee", "casscf", None)),
                    ("without a method", ("opt", "min", None, None))]:
    other = capability_answer(*args)
    check(f"the same list is returned {label}",
          bool(other.get("parameters")), f"{len(other.get('parameters') or [])} parameter(s)")

size = len(str(answer))
check("the answer stays a reasonable size to carry in a conversation",
      size < 8000, f"{size} chars, roughly {size // 3} tokens")

print("\n== an empty conversation does not reach the model ==")
import app.agent.graph as graph_mod  # noqa: E402

buf, lg, handler = capture("app.agent.graph")
result = graph_mod._agent_node({"messages": []})
produced = result["messages"][0]
check("it answers instead of calling the model",
      isinstance(produced, AIMessage) and bool(produced.content),
      repr(str(produced.content)[:90]))
check("in words a user can act on, naming no internals",
      "500" not in str(produced.content) and "SystemMessage" not in str(produced.content))
check("and says so in the log", "no history" in buf.getvalue(), buf.getvalue()[:120])
lg.removeHandler(handler)

# The guard must not fire on a conversation that does have history: the
# trimmer can legitimately return a short window, and refusing then would
# replace a working turn with an apology.
kept = graph_mod._trim_history([HumanMessage(content="hello")])
check("a conversation with one real message is not caught by the guard",
      len(kept) == 1, f"{len(kept)} message(s) kept")

print("\n== erasing a stopped turn's output says so ==")
from server.routes import chat as chat_mod  # noqa: E402

buf, lg, handler = capture("server.routes.chat")
erased = []
original = chat_mod.remove_messages
chat_mod.remove_messages = lambda config, ids: erased.append(ids) or {"messages": []}
try:
    chat_mod._erase_phantom_messages("thread-abc", {}, ["m1", "m2"])
finally:
    chat_mod.remove_messages = original
lg.removeHandler(handler)

logged = buf.getvalue()
check("the messages are still erased", erased == [["m1", "m2"]], str(erased))
check("the thread is named", "thread-abc" in logged, logged[:140])
check("so is how many went", "2 message(s)" in logged, logged[:140])
check("and it is not dressed up as an error",
      "not an error" in logged, logged[:160])

print(f"\n{PASS}/{PASS + FAIL} checks passed")
sys.exit(1 if FAIL else 0)
