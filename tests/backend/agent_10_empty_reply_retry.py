"""An empty model reply must never end a turn in silence.

On 2026-09-24 a model call ran for 106 s and returned an AIMessage with no
content and no tool call. `_should_continue` routes a reply with no tool
call to END, so the turn finished on nothing: no chat bubble, no log line,
and a user who typed "hello?" six minutes later to get their answer.

`_agent_node` now retries such a reply once and, if the retry is empty as
well, answers with one fixed sentence instead. This checks the three paths by
standing in for the model with a scripted fake. No stack, no Ollama.

  1. empty, then a real reply  -> two calls, the real reply is the output
  2. empty twice               -> two calls, the fixed fallback sentence
  3. a real reply first time   -> one call, returned untouched
  4. a reply cut off by finish_reason=length is NOT retried (a retry would
     hit the same full prompt; _warn_if_truncated reports that case)
  5. a tool call with no text is NOT empty

Run:  PYTHONPATH=$PWD python3 tests/backend/agent_10_empty_reply_retry.py
"""
import sys

from langchain_core.messages import AIMessage, HumanMessage

from app.agent import graph

failures = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


class ScriptedModel:
    """Returns the scripted replies in order and counts the calls."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        return self.replies.pop(0)


def run(replies):
    model = ScriptedModel(replies)
    original = graph._build_llm
    graph._build_llm = lambda: model
    try:
        out = graph._agent_node({"messages": [HumanMessage(content="table of S1 and S2, please")],
                                 "active_job_ids": []})
    finally:
        graph._build_llm = original
    return model.calls, out["messages"][-1]


empty = lambda **kw: AIMessage(content="", response_metadata={"finish_reason": "stop", **kw})

calls, msg = run([empty(), AIMessage(content="| state | eV |")])
check("empty then real: retried exactly once", calls == 2, "calls=%d" % calls)
check("empty then real: the real reply is what the turn returns",
      msg.content == "| state | eV |", repr(msg.content))

calls, msg = run([empty(), empty()])
check("empty twice: still only two calls", calls == 2, "calls=%d" % calls)
check("empty twice: the user gets the fallback sentence, not silence",
      msg.content == graph._EMPTY_REPLY_FALLBACK, repr(msg.content))

calls, msg = run([AIMessage(content="Here it is.")])
check("a real first reply is not retried", calls == 1 and msg.content == "Here it is.")

cut = AIMessage(content="", response_metadata={"finish_reason": "length"})
check("a length-truncated reply is not treated as empty", not graph._is_empty_reply(cut))

tool_only = AIMessage(content="", tool_calls=[{"name": "check_job_status", "args": {}, "id": "c1"}])
check("a tool call with no text is not treated as empty", not graph._is_empty_reply(tool_only))

whitespace = AIMessage(content="  \n", response_metadata={"finish_reason": "stop"})
check("whitespace-only content counts as empty", graph._is_empty_reply(whitespace))

print()
print("%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
