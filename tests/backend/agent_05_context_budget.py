"""Context-budget regression: a long conversation must leave room to answer in.

Replays the two turns from a real conversation that were cut off mid-sentence
with finish_reason "length" before they could emit a submit_draft tool call,
so the job-approval card silently never appeared. Both prompts had reached
~65,433 tokens against a 65,536-token server window, leaving about 100 tokens
of output budget.

The failure was invisible: a clean HTTP 200, a normally-completed graph turn,
a well-formed checkpoint message that happened to stop mid-word. So this
asserts on the number, not on the reply looking fine -- a short answer can
complete at the very top of the window and still look like a pass.

Needs the configured Ollama endpoint to be up. If it is not, this reports
SKIPPED rather than failing, for the reason agent_01_token_budget.py gives:
a red result that means "the server is down" teaches people to ignore red
results.

Run:  PYTHONPATH=$PWD python3 tests/backend/agent_05_context_budget.py

The synthetic case needs nothing but the model. Replaying a real stored
conversation additionally needs the checkpointer that holds it, which in
the compose deployment is Postgres and is only reachable from inside the
container:

    docker compose cp tests/backend/agent_05_context_budget.py api:/tmp/t.py
    docker compose exec -T -e QC_AGENT_TEST_THREAD_ID=<thread_id> api python3 /tmp/t.py
"""
import os
import sys

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.agent.graph import (  # noqa: E402
    SYSTEM_PROMPT, _build_llm, _digest_line, _estimate_tokens, _history_token_budget, build_prompt_messages,
    _message_tokens, _trim_history, _get_checkpointer,
)
from app.config import (  # noqa: E402
    LLM_FIXED_PROMPT_TOKENS, LLM_HISTORY_FLOOR, LLM_HISTORY_WINDOW, LLM_MAX_TOKENS,
    LLM_NUM_CTX, LLM_OUTPUT_RESERVE_TOKENS,
)

failures = []


def model_reachable():
    import urllib.error
    import urllib.request
    from app.config import LLM_BASE_URL
    try:
        urllib.request.urlopen(LLM_BASE_URL.rstrip("/") + "/models", timeout=5).read(1)
        return True
    except (urllib.error.URLError, OSError):
        return False


def check(label, ok, detail):
    print(("[PASS] " if ok else "[FAIL] ") + label + " -- " + detail)
    if not ok:
        failures.append(label)


def build_prompt(prior, state):
    """The real assembly, not a copy of it.

    This used to reproduce _agent_node's prompt building here, which is a
    thing that silently stops matching: when the digest moved out of the
    system message and the window became sticky, this copy would have gone
    on measuring the old shape and reporting it as healthy.
    """
    return build_prompt_messages({**state, "messages": prior})


def run_case(label, prior, state):
    messages = build_prompt(prior, state)
    response = _build_llm().invoke(messages)
    metadata = response.response_metadata or {}
    usage = metadata.get("token_usage") or {}
    prompt_tokens = usage.get("prompt_tokens")
    finish = metadata.get("finish_reason")

    print("\n--- %s ---" % label)
    print("    window %d of %d messages, prompt_tokens=%s, finish_reason=%s"
          % (len(messages) - 1, len(prior), prompt_tokens, finish))

    check("%s: reply not truncated" % label, finish != "length",
          "finish_reason=%s" % finish)

    if prompt_tokens is not None:
        ceiling = LLM_NUM_CTX - LLM_OUTPUT_RESERVE_TOKENS
        check("%s: output reserve intact" % label, prompt_tokens <= ceiling,
              "prompt %d tokens, must stay at or under %d (context %d minus reserve %d)"
              % (prompt_tokens, ceiling, LLM_NUM_CTX, LLM_OUTPUT_RESERVE_TOKENS))
        headroom = LLM_NUM_CTX - prompt_tokens
        check("%s: room for a full-length reply" % label, headroom >= LLM_MAX_TOKENS,
              "%d tokens of headroom, max_tokens is %d" % (headroom, LLM_MAX_TOKENS))


def synthetic_case():
    """A conversation of oversized job results, built rather than stored.

    LLM_HISTORY_WINDOW messages each the size of a real check_job_status
    result. Under the old message-count-only trim this is exactly the shape
    that overran the window.
    """
    bulk = "\n".join(
        "  %2d  %14.8f %14.8f %14.8f" % (i, i * 0.11, i * -0.22, i * 0.33)
        for i in range(420)
    )
    prior = []
    for turn in range(LLM_HISTORY_WINDOW):
        prior.append(HumanMessage(content="check job %d please" % turn))
        prior.append(ToolMessage(
            content="Job %012d completed.\n%s" % (turn, bulk),
            tool_call_id="call_%d" % turn, name="check_job_status",
        ))
    prior.append(HumanMessage(content="Summarise the last result in one sentence."))
    state = {"messages": prior, "molecule": {"name": "uracil", "formula": "C4H4N2O2"},
             "active_job_ids": ["%012d" % t for t in range(3)]}
    run_case("synthetic oversized history", prior, state)


def stored_case(thread_id):
    """Every prefix of a real conversation must trim to something that fits.

    Two passes, because they cost wildly different amounts. The sweep is
    the trimmer's own contract checked against its own estimator -- no
    model call, so it can cover every turn in the conversation and stays
    stable as the thread grows. The live pass then checks the estimator
    itself against the served tokenizer on a few prefixes, which is the
    half that would otherwise be self-congratulatory: a budget kept
    perfectly against a wrong estimate is exactly how this bug happened.
    """
    checkpoint = _get_checkpointer().get_tuple({"configurable": {"thread_id": thread_id}})
    if checkpoint is None:
        print("[SKIP] no checkpoint for thread %s" % thread_id)
        return
    values = dict(checkpoint.checkpoint["channel_values"])
    full = values["messages"]
    budget = _history_token_budget()

    print("\n--- sweep: %d prefixes of thread %s ---" % (len(full), thread_id))
    over = []
    for cut in range(2, len(full) + 1):
        history = _trim_history(full[:cut])
        used = sum(_message_tokens(m) for m in history)
        # Over budget is only acceptable when LLM_HISTORY_FLOOR is what is
        # holding the messages in, i.e. nothing further can be dropped.
        if used > budget and len(history) > LLM_HISTORY_FLOOR:
            over.append((cut, used, len(history)))
    check("every prefix trims within budget", not over,
          "%d prefix(es) over budget: %s" % (len(over), over[:3]) if over
          else "all %d prefixes within %d tokens" % (len(full) - 1, budget))

    # Prefixes worth spending a real call on: the ends, and any that the
    # estimator puts within 15% of the ceiling, where a wrong estimate
    # actually costs something.
    ceiling = LLM_NUM_CTX - LLM_OUTPUT_RESERVE_TOKENS
    tight = [
        cut for cut in range(2, len(full) + 1)
        if sum(_message_tokens(m) for m in _trim_history(full[:cut])) > 0.85 * budget
    ]
    live = sorted({len(full), tight[0] if tight else 2, tight[-1] if tight else len(full)})
    for cut in live:
        prior = full[:cut]
        run_case("stored thread cut at %d" % cut, prior, {**values, "messages": prior})


def dedupe_case():
    """The same job attached on a later turn must not repeat its results.

    The Job Manager's "Attach to prompt" stays on across turns, so the
    frontend re-sends the same job ids with every message. Each expansion is
    around 20,000 characters of numeric tables, and in the conversation that
    exposed this it happened three times for one job -- roughly 30,000
    tokens, close to half the window, spent on two redundant copies.
    """
    from server.routes.chat import _JOB_ATTACH_PREFIX, _attached_job_messages

    jid = "51a14d838f5b"
    prefix = _JOB_ATTACH_PREFIX.format(jid=jid)
    fresh = _attached_job_messages({"messages": []}, [jid])
    check("a job not yet in the history is attached in full", len(fresh) == 1,
          "%d message(s)" % len(fresh))

    already = {"messages": [HumanMessage(content=prefix + " Job %s completed. <results>" % jid)]}
    repeat = _attached_job_messages(already, [jid])
    check("a job already in the history is not repeated",
          len(repeat) == 1 and len(str(repeat[0].content)) < 400,
          "second attach is %d chars" % len(str(repeat[0].content)))
    check("the pointer still names the job so 'this job' resolves",
          jid in str(repeat[0].content),
          repr(str(repeat[0].content)[:90]))

    other = _attached_job_messages(already, ["a4a45e5403df"])
    check("a different job is still attached in full",
          len(other) == 1 and "already in this conversation" not in str(other[0].content),
          "%d chars" % len(str(other[0].content)))


print("context %d, fixed prompt %d, output reserve %d -> history budget %d tokens (~%d chars)"
      % (LLM_NUM_CTX, LLM_FIXED_PROMPT_TOKENS, LLM_OUTPUT_RESERVE_TOKENS,
         _history_token_budget(), _history_token_budget() * 2))
check("history budget is usable", _history_token_budget() > 4000,
      "%d tokens" % _history_token_budget())
# The estimator must never under-count, and numeric content is where a flat
# chars/token ratio does: floats tokenize at roughly one token per character.
_NUMERIC = "  12  -412.57384912   0.00031845  17.90210000\n" * 400
_PROSE = "The active space spans the pi system and the oxygen lone pairs. " * 300
check("estimator does not under-count numeric content",
      _estimate_tokens(_NUMERIC) >= len(_NUMERIC) * 0.8,
      "%d chars -> %d tokens" % (len(_NUMERIC), _estimate_tokens(_NUMERIC)))
check("estimator does not under-count prose",
      _estimate_tokens(_PROSE) >= len(_PROSE) / 4.0,
      "%d chars -> %d tokens" % (len(_PROSE), _estimate_tokens(_PROSE)))

dedupe_case()

if not model_reachable():
    print("\n[SKIPPED] model endpoint unreachable -- the live token measurements did not run")
    print("\n%d failure(s)" % len(failures))
    sys.exit(1 if failures else 0)

synthetic_case()

thread_id = os.environ.get("QC_AGENT_TEST_THREAD_ID", "").strip()
if thread_id:
    stored_case(thread_id)
else:
    print("\n[note] set QC_AGENT_TEST_THREAD_ID to also replay a stored conversation")

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
