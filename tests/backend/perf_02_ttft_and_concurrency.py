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

Run:
    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 PYTHONPATH=$PWD \\
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
    qatest_username, register, summary,
)

# Answerable from the model alone: no molecule, no draft, no job.
PROMPT = "In two sentences, what is the difference between HF and DFT?"

N_WARMUP = 1
N_SERIAL = 6          # TTFT samples, one at a time
N_CONCURRENT = 4      # the deployment's stated requirement
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

        # --- four at once --------------------------------------------------
        threads_ids = [_new_conversation(c, "concurrent") for c in clients]
        results: list = [None] * N_CONCURRENT
        barrier = threading.Barrier(N_CONCURRENT)

        def one(i: int):
            barrier.wait()
            results[i] = _first_visible(clients[i], threads_ids[i], PROMPT)

        workers = [threading.Thread(target=one, args=(i,)) for i in range(N_CONCURRENT)]
        wall_start = time.monotonic()
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=TURN_TIMEOUT + 60)
        wall = time.monotonic() - wall_start

        got = [r for r in results if r]
        for i, (ttft, total, ntok) in enumerate(got):
            print(f"  user {i + 1}: first output {ttft:5.2f}s, turn {total:6.2f}s, "
                  f"{ntok} token events")
        c_ttft = [x[0] for x in got]
        c_total = [x[1] for x in got]
        c_rate = [x[2] / x[1] for x in got if x[1] > 0]
        print(f"\n  {N_CONCURRENT} at once: TTFT median {statistics.median(c_ttft):.2f}s, "
              f"turn median {statistics.median(c_total):.2f}s, "
              f"token events/s median {statistics.median(c_rate):.1f}")
        print(f"  wall clock for all {N_CONCURRENT}: {wall:.2f}s "
              f"(serially it would be about {statistics.median(s_total) * N_CONCURRENT:.0f}s)\n")

        # --- what the numbers have to clear -------------------------------
        check("every concurrent turn completed", len(got) == N_CONCURRENT,
              f"{len(got)}/{N_CONCURRENT}")
        check("warm TTFT is under 10s at the median",
              statistics.median(s_ttft) < 10,
              f"median {statistics.median(s_ttft):.2f}s")
        # The honest concurrency question: does a fourth user make the first
        # one wait unreasonably? Time-slicing would show as TTFT scaling with
        # the number of users; real batching keeps it closer to flat.
        ratio = statistics.median(c_ttft) / max(statistics.median(s_ttft), 1e-6)
        check("TTFT with four users is under 3x the single-user median",
              ratio < 3.0, f"{ratio:.2f}x")
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
