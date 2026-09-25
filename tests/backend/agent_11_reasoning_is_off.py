"""The served model must not be reasoning behind the reply.

`LLM_EXTRA_BODY` (app/config.py) is what switches a hybrid model's thinking
off. The previous setting, `think: false` alone, stopped working on an Ollama
upgrade without any error: the /v1 endpoint accepted it and ignored it, and
the reasoning streamed in a `reasoning` field that ChatOpenAI discards. So
nothing in the app could see it. It showed up only as slower turns, and once
as a 106 s turn that ended with no visible reply.

This asks the served model the same short question three ways and reads the
raw response, where the reasoning field IS visible:

  1. with LLM_EXTRA_BODY           -> must carry no reasoning text
  2. with `think: false` alone     -> reported, not asserted: it shows
                                      whether the old setting still leaks
  3. through ChatOpenAI + all tools with LLM_EXTRA_BODY, as the agent
     calls it -> completion tokens are reported beside the visible reply

Needs a reachable model. On a host where the stack's .env names
host.docker.internal, run it with QC_AGENT_LLM_BASE_URL pointed at the host.

Run:  PYTHONPATH=$PWD python3 tests/backend/agent_11_reasoning_is_off.py
"""
import sys

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import get_all_tools
from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_EXTRA_BODY, LLM_MAX_TOKENS, LLM_MODEL

failures = []
QUESTION = ("Summarise in a markdown table: CASSCF S1 5.13 S2 6.74 eV; "
            "CASPT2 S1 4.93 S2 5.17 eV. Two jobs failed.")


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("  -- %s" % detail) if detail else ""))
    if not ok:
        failures.append(name)


def raw(body):
    r = httpx.post(f"{LLM_BASE_URL}/chat/completions", timeout=300, json={
        "model": LLM_MODEL, "max_tokens": 2000, "temperature": 0.0,
        "messages": [{"role": "user", "content": QUESTION}], **body})
    r.raise_for_status()
    d = r.json()
    m = d["choices"][0]["message"]
    reasoning = m.get("reasoning") or m.get("reasoning_content") or ""
    return len(m.get("content") or ""), len(reasoning), d.get("usage", {}).get("completion_tokens")


# Skipped, not failed, when no model answers: a full tests/run_backend.sh run
# on a host whose .env names host.docker.internal reaches no model from here,
# and a traceback there would read as a regression. Same rule as agent_01.
try:
    content, reasoning, tokens = raw(LLM_EXTRA_BODY)
except httpx.HTTPError as e:
    print(f"[SKIPPED] the model at {LLM_BASE_URL} is not reachable: {type(e).__name__}: {e}")
    sys.exit(0)
check("LLM_EXTRA_BODY: no hidden reasoning comes back", reasoning == 0 and content > 0,
      "%d reply chars, %d reasoning chars, %s completion tokens" % (content, reasoning, tokens))

content, reasoning, tokens = raw({"think": False})
print("[INFO] think:false alone: %d reply chars, %d reasoning chars, %s completion tokens"
      % (content, reasoning, tokens))

llm = ChatOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, model=LLM_MODEL, temperature=0.0,
                 extra_body=LLM_EXTRA_BODY, timeout=300, max_retries=0,
                 max_tokens=LLM_MAX_TOKENS).bind_tools(get_all_tools())
reply = llm.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=QUESTION)])
tokens = (reply.response_metadata.get("token_usage") or {}).get("completion_tokens")
chars = len(str(reply.content or ""))
# A token is ~3-4 characters of English/markdown. With reasoning on, the same
# reply cost more tokens than it had characters/2; 1 token per 2 characters
# is a generous ceiling for a reply with nothing hidden behind it.
check("as the agent calls it: completion tokens match the visible reply",
      tokens is not None and chars > 0 and tokens <= chars / 2 + 20,
      "%d reply chars, %s completion tokens" % (chars, tokens))

print()
print("%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
