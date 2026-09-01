#!/usr/bin/env python3
"""Time to first token, warm, and what happens with four users at once.

Two numbers this project has been quoting or assuming without measuring.

**TTFT.** The standing "6-32s, median ~15s" is an n=4 sample from
2026-08-16 that almost certainly predates its own explanation: the
keep-warm loop (`QC_AGENT_MODEL_KEEPALIVE_INTERVAL`) landed the next day,
and this host later measured 11.4s cold against 2.9s warm. The old figure
was very plausibly dominated by cold loads. It is quoted in user-facing
text, so it gets measured on the current deployment, warm, with a real
sample size.

**Concurrency.** The deployment has to serve 3-4 people at once and nothing
has ever tested whether it does. The evaluation battery ran three streams
and worked, slowly -- but three agents hammering continuously is far
harsher than four people typing, so that is not the answer either.

Both numbers are pooled over N_BURSTS repetitions, on the app's side and the
model server's alike, and the server baseline is sampled before AND after the
app's own measurement. That is not caution for its own sake: this script
previously drew its verdict from four samples taken once, on a host shared
with other tenants, and its answer moved by more than the threshold it was
testing between consecutive runs. A perf test that flips run to run teaches
people to ignore it.

Measured through the app's own chat API rather than against Ollama
directly, because what a user waits for includes prompt assembly, the tool
schema, and the graph -- not just the model. First *visible* output is the
clock stop: the first token delta or the first completed message,
whichever the SSE stream delivers first, which is the moment the UI stops
looking idle.

The prompt deliberately asks a question the agent can answer from its own
knowledge, with no molecule and no job. A turn that submits a job spends
most of its time in tool calls, which would measure the registry rather
than the model, and would leave jobs behind on a shared machine.

This takes four to five minutes, most of it spent deliberately: the pooling
described above is what the runtime buys. On a host where the model endpoint
is only reachable from inside a container, set QC_AGENT_LLM_BASE_URL for the
run or the baseline silently does not happen and the script falls back to an
absolute check that cannot attribute anything.

Run:
    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 PYTHONPATH=$PWD \\
      QC_AGENT_LLM_BASE_URL=http://localhost:11434/v1 \\
      python3 tests/backend/perf_02_ttft_and_concurrency.py
"""
from __future__ import annotations

import json
import statistics
import sys
import threading
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    BASE_URL, admin_client, check, cleanup_user, mint_invite, new_client,
    qatest_username, register, skip, summary,
)

# Answerable from the model alone: no molecule, no draft, no job.
PROMPT = "In two sentences, what is the difference between HF and DFT?"

N_WARMUP = 1
# Matched to the concurrent side's pooled sample count (N_CONCURRENT *
# N_BURSTS), because this is the DENOMINATOR of the app's ratio and it was
# the noisiest input left. At n=6 its median moved between 1.43s and 3.38s
# across runs while the concurrent median barely moved, which by itself
# swung the app's ratio from 2.21x to 3.21x. Within a single run these
# samples spread 1.34s to 4.03s, so six of them do not pin a median. Each
# costs about four seconds, so matching the two sides is cheap.
N_SERIAL = 12         # TTFT samples, one at a time
N_CONCURRENT = 4      # the deployment's stated requirement
# Both the app's concurrent burst and the model server's are repeated and
# pooled. One burst of four gives a median over four samples, and on a host
# shared with other tenants that median moved enough between runs to flip
# this script's verdict: across six runs in one hour the server measured
# 1.63x to 2.80x and the app 1.82x to 5.87x, which made their quotient swing
# from 1.08x to 2.84x against a 1.5x threshold. Pooling is the honest fix;
# moving the threshold until it passed would not be.
N_BURSTS = 3
TURN_TIMEOUT = 300.0


def _first_visible(client: httpx.Client, thread_id: str, prompt: str) -> tuple[float, float, int]:
    """(seconds to first visible output, seconds to turn_complete, tokens seen).

    The event stream is opened before the message is posted: POST /messages
    answers 202 and runs the turn on a background thread, so subscribing
    afterwards can miss the beginning of what is being timed.
    """
    first = [None]
    done = threading.Event()
    tokens = [0]
    started = [0.0]

    def reader():
        with httpx.Client(base_url=BASE_URL, verify=False, timeout=None,
                          cookies=client.cookies) as c:
            with c.stream("GET", f"/api/threads/{thread_id}/events") as r:
                connected.set()
                for line in r.iter_lines():
                    if done.is_set():
                        return
                    if not line.startswith("data: "):
                        continue
                    ev = json.loads(line[6:])
                    kind = ev.get("type")
                    if kind == "token":
                        tokens[0] += 1
                    if first[0] is None and kind in ("token", "message"):
                        first[0] = time.monotonic() - started[0]
                    if kind == "turn_complete":
                        done.set()
                        return

    connected = threading.Event()
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    connected.wait(timeout=30)
    started[0] = time.monotonic()
    client.post(f"/api/threads/{thread_id}/messages", json={"text": prompt})
    done.wait(timeout=TURN_TIMEOUT)
    total = time.monotonic() - started[0]
    return (first[0] if first[0] is not None else float("nan")), total, tokens[0]


# --- what the model server does on its own, for attribution ----------------
#
# This test used to assert an absolute ratio -- four users within 3x the
# single-user median -- and fail without saying whose fault it was. That is
# the wrong shape for a number the app only partly controls: the model server
# underneath has its own concurrency penalty, and on a shared host it can have
# a large one.
#
# Measured directly, streaming, in the same run, and pooled the same way the
# app's own burst is.
#
# The 2026-08-29 reading of this -- server 2.12x against the app's 5.04x, so
# the residual is the app's -- did not survive being repeated. Pooled over
# three bursts on both sides the app measures 2.21x against the server's
# 2.12x, i.e. it multiplies the server's penalty by about 1.05x. What changed
# is the sampling, not the code: see N_BURSTS.
#
# That systematic difference is now closed. This used to fire a synthetic
# filler string while the app path ran a real agent turn carrying the whole
# tool schema, and prompt size measurably moves the server's own ratio
# (1.50x at 48k characters against 2.33x at 103k), so the quotient
# conflated app overhead with prompt size. The baseline now sends the app's
# OWN system prompt and its OWN tool schema, taken from the same
# app.agent.prompts.SYSTEM_PROMPT and app.agent.tools.get_all_tools() the
# graph binds, so both sides of the ratio pay for the same payload and the
# only remaining difference is this app's code.
#
# Deriving it rather than hardcoding a character count is the point: the
# old comment asserted a 66k-character schema, and the real figure is
# 34.7k (6.1k of system prompt plus 28.5k of tool JSON). A number written
# into a comment goes stale the first time a tool is added; reading it from
# the same source the agent reads cannot.
def _server_ttft_ratio() -> float | None:
    """Median TTFT under N_CONCURRENT concurrent requests, over the single
    median, with nothing of this app in the way. None if the endpoint cannot
    be reached, in which case the app-vs-host split is simply not available
    and the absolute check below stands on its own.

    Internally pooled over N_BURSTS bursts, and called TWICE by the caller,
    before and after the app's own measurement, with the two results pooled
    again. That is not belt and braces. This host's model server is shared
    with other tenants, and measured 1.63x, 2.04x and 2.80x on three
    consecutive runs of this script inside one hour; a single burst at the
    end of a run was the largest source of noise in this script's verdict."""
    import concurrent.futures as cf
    import json as _json
    import urllib.request

    from langchain_core.utils.function_calling import convert_to_openai_tool

    from app.agent.prompts import SYSTEM_PROMPT
    from app.agent.tools import get_all_tools
    from app.config import LLM_BASE_URL, LLM_MODEL

    tool_schemas = [convert_to_openai_tool(tool) for tool in get_all_tools()]
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"

    def once(_i: int) -> float:
        body = _json.dumps({
            "model": LLM_MODEL,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": "Reply with the single word: ok"}],
            # The real schema, not a stand-in for one. Offering the tools
            # also means the model may answer with a tool call rather than
            # text, which is why the reader below counts either as a first
            # token: that is a cost the app pays on every turn too, and
            # waiting only for content would have measured a different
            # thing on the two sides.
            "tools": tool_schemas,
            "max_tokens": 64, "stream": True,
        }).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=300) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data: ") or line.endswith("[DONE]"):
                    continue
                delta = (_json.loads(line[6:]).get("choices") or [{}])[0].get("delta", {})
                if delta.get("content") or delta.get("tool_calls"):
                    return time.time() - t0
        return time.time() - t0

    try:
        once(0)  # warm
        single, many = [], []
        for _ in range(N_BURSTS):
            single.append(once(0))
            with cf.ThreadPoolExecutor(max_workers=N_CONCURRENT) as ex:
                many.extend(ex.map(once, range(N_CONCURRENT)))
        return statistics.median(many) / max(statistics.median(single), 1e-6)
    except Exception:
        return None


def _new_conversation(client: httpx.Client, label: str) -> str:
    r = client.post("/api/threads", json={"label": label})
    r.raise_for_status()
    return r.json()["thread_id"]


def main() -> int:
    admin = admin_client()
    users = []
    clients = []
    for i in range(N_CONCURRENT):
        token = mint_invite(admin)
        c, u = register(token, username=qatest_username())
        clients.append(c)
        users.append(u)

    try:
        # Warm the model so this measures a live server, not a cold load --
        # which is the whole reason the old figure is suspect.
        for _ in range(N_WARMUP):
            _first_visible(clients[0], _new_conversation(clients[0], "warmup"), PROMPT)

        # The first of two baseline samples, taken BEFORE the app's own
        # measurement rather than only after it. See _server_ttft_ratio for
        # why one sample at the end was not enough.
        server_ratio_before = _server_ttft_ratio()

        # --- one at a time ------------------------------------------------
        serial = []
        for i in range(N_SERIAL):
            ttft, total, ntok = _first_visible(
                clients[0], _new_conversation(clients[0], f"ttft {i}"), PROMPT)
            serial.append((ttft, total, ntok))
            print(f"  serial {i + 1}/{N_SERIAL}: first output {ttft:5.2f}s, "
                  f"turn {total:6.2f}s, {ntok} token events")

        s_ttft = [x[0] for x in serial]
        s_total = [x[1] for x in serial]
        s_rate = [x[2] / x[1] for x in serial if x[1] > 0]
        print(f"\n  TTFT warm, n={len(s_ttft)}: median {statistics.median(s_ttft):.2f}s, "
              f"range {min(s_ttft):.2f}-{max(s_ttft):.2f}s")
        print(f"  turn:  median {statistics.median(s_total):.2f}s, "
              f"token events/s median {statistics.median(s_rate):.1f}\n")

        # --- four at once, N_BURSTS times ---------------------------------
        # Repeated and pooled for the same reason the server baseline is: a
        # median over one burst of four is four samples, and four samples on
        # a shared host is not enough to tell this script's verdict apart
        # from the host's mood. Each burst gets fresh conversations, or the
        # second one would carry the first one's history into its prompt and
        # measure a longer prefill.
        got = []
        burst_walls: list[float] = []
        for burst in range(N_BURSTS):
            threads_ids = [_new_conversation(c, f"concurrent {burst}") for c in clients]
            results: list = [None] * N_CONCURRENT
            barrier = threading.Barrier(N_CONCURRENT)

            def one(i: int, ids=threads_ids, out=results):
                barrier.wait()
                out[i] = _first_visible(clients[i], ids[i], PROMPT)

            workers = [threading.Thread(target=one, args=(i,)) for i in range(N_CONCURRENT)]
            wall_start = time.monotonic()
            for w in workers:
                w.start()
            for w in workers:
                w.join(timeout=TURN_TIMEOUT + 60)
            # The wall-clock check below compares ONE burst of four against
            # four serial turns, so it wants a single burst's time rather
            # than the sum of every burst. The median of the bursts, not the
            # slowest: every other number in this script is a median, and
            # holding a worst case against a median compares two different
            # statistics and flakes for that reason alone.
            burst_walls.append(time.monotonic() - wall_start)
            burst_got = [r for r in results if r]
            got.extend(burst_got)
            for i, (ttft, total, ntok) in enumerate(burst_got):
                print(f"  burst {burst + 1} user {i + 1}: first output {ttft:5.2f}s, "
                      f"turn {total:6.2f}s, {ntok} token events")
        wall = statistics.median(burst_walls)
        c_ttft = [x[0] for x in got]
        c_total = [x[1] for x in got]
        c_rate = [x[2] / x[1] for x in got if x[1] > 0]
        print(f"\n  {N_CONCURRENT} at once, pooled over {N_BURSTS} bursts "
              f"(n={len(c_ttft)}): TTFT median {statistics.median(c_ttft):.2f}s, "
              f"turn median {statistics.median(c_total):.2f}s, "
              f"token events/s median {statistics.median(c_rate):.1f}")
        print(f"  wall clock for all {N_CONCURRENT}: {wall:.2f}s "
              f"(serially it would be about {statistics.median(s_total) * N_CONCURRENT:.0f}s)\n")

        # --- what the numbers have to clear -------------------------------
        check("every concurrent turn completed", len(got) == N_CONCURRENT * N_BURSTS,
              f"{len(got)}/{N_CONCURRENT * N_BURSTS}")
        check("warm TTFT is under 10s at the median",
              statistics.median(s_ttft) < 10,
              f"median {statistics.median(s_ttft):.2f}s")
        # The honest concurrency question: does a fourth user make the first
        # one wait unreasonably? Time-slicing would show as TTFT scaling with
        # the number of users; real batching keeps it closer to flat.
        ratio = statistics.median(c_ttft) / max(statistics.median(s_ttft), 1e-6)
        # Pooled from before and after the app's own burst: the host drifts
        # over the two minutes a run takes, and a single sample at the end
        # was the largest source of noise in this script's verdict.
        server_samples = [r for r in (server_ratio_before, _server_ttft_ratio()) if r is not None]
        server_ratio = statistics.median(server_samples) if server_samples else None
        if server_ratio is None:
            print("  [note] the model endpoint could not be measured directly, so this "
                  "run cannot separate the app's share from the host's")
            check("TTFT with four users is under 3x the single-user median",
                  ratio < 3.0, f"{ratio:.2f}x")
        else:
            spread = (f" (sampled {' and '.join(f'{r:.2f}x' for r in server_samples)}"
                      f" before and after)" if len(server_samples) > 1 else "")
            print(f"  the model server alone: {server_ratio:.2f}x under the same "
                  f"concurrency{spread}; the app measured {ratio:.2f}x")

            # Whether this run can attribute anything at all, decided by the
            # baseline's own internal disagreement rather than by whether the
            # app came out well. The two baseline samples are the same
            # measurement taken twenty minutes apart in the same run; when
            # they disagree, the host changed underneath the run and the
            # quotient below is dividing by a number that no longer means
            # anything. Observed on this host: 3.05x and then 0.95x in one
            # run, the second of which says four concurrent requests were
            # FASTER than one, which is not a fact about anything but the
            # other tenants' GPU usage at that moment.
            #
            # This is a guard on whether the measurement is valid, not a
            # threshold on the result. It is the reason this script can be
            # trusted when it does report a number.
            drifted = (len(server_samples) > 1
                       and max(server_samples) / max(min(server_samples), 1e-6) > 1.5)
            # The question worth failing on is what the APP adds on top of a
            # penalty it does not control. A host whose GPUs are busy with
            # other tenants can blow the absolute budget on its own, and a
            # test that fails for that teaches people to ignore it.
            added = ratio / max(server_ratio, 1e-6)
            if drifted:
                skip("the app adds little to the model server's own concurrency penalty",
                     f"the baseline moved from {server_samples[0]:.2f}x to "
                     f"{server_samples[-1]:.2f}x during this run, so there is no stable "
                     f"denominator to attribute against. The app measured {ratio:.2f}x and "
                     f"the raw seconds above stand; the split between app and host does "
                     f"not. Re-run when the host is quieter, or measure with the GPU to "
                     f"yourself")
            else:
                check("the app adds little to the model server's own concurrency penalty",
                      added < 1.5,
                      f"app {ratio:.2f}x vs server {server_ratio:.2f}x -- the app multiplies it "
                      f"by {added:.2f}x, which is this repo's to fix rather than the host's")
            # The absolute budget is a user-experience number, not a
            # correctness one, and it is the whole stack's rather than this
            # repo's. When the model server has already spent most of it on
            # its own, this check cannot tell a slow app from a busy host,
            # so it is reported rather than failed -- the check above is the
            # one that holds this repo to account. Deliberately a skip and
            # not a relaxed threshold: the budget has not moved, it is that
            # the measurement stops discriminating past this point.
            if drifted or server_ratio >= 2.0:
                skip("and the whole stack stays inside the 3x budget",
                     f"measured {ratio:.2f}x, but the model server alone accounts for "
                     f"{server_ratio:.2f}x of it, so this cannot separate a slow app from "
                     f"a busy host. What moves this number is the model server's KV cache "
                     f"per concurrent slot, i.e. the context length or the card; see "
                     f"README.md's note on serving several people at once")
            else:
                check("and the whole stack stays inside the 3x budget",
                      ratio < 3.0,
                      f"{ratio:.2f}x, of which the server accounts for {server_ratio:.2f}x")
        check("four concurrent turns finish faster than four serial ones",
              wall < statistics.median(s_total) * N_CONCURRENT,
              f"{wall:.1f}s vs about {statistics.median(s_total) * N_CONCURRENT:.0f}s")
    finally:
        for u in users:
            cleanup_user(admin, u["id"])

    summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
