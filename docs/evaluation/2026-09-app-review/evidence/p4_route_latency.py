#!/usr/bin/env python3
"""P4.2 and P4.3: route latency and per-tab polling cost, measured against the
frozen deployment (ca7e0ff).

P4.2 times the read routes a loaded deployment leans on, at whatever job count
the stack currently holds, and reports p50/p95 over N samples each. It does NOT
seed hundreds of jobs of its own -- the review's hygiene rule is to leave the
stack as it was found, and P3.5 already exercises the list under a deliberate
seed that it then removes. So this measures the routes at the real current
size and records that size, which is the honest, reproducible thing.

P4.3 counts the API requests one idle authenticated tab makes per minute, by
reading them from the browser (that half runs in the P3 drivers); here we
measure the server side: latency of /api/threads/{id}/state, the single most
polled route, at the sizes we have.

Run with the stack up and the qc-agent env active:

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 PYTHONPATH=$PWD \
      QC_REVIEW_ACCOUNTS=<scratchpad>/review-accounts.json \
      python3 docs/evaluation/2026-09-app-review/evidence/p4_route_latency.py
"""
from __future__ import annotations
import json, os, statistics, sys, time
from pathlib import Path

sys.path.insert(0, "tests")
from fixtures import admin_client, new_client  # noqa: E402
import httpx  # noqa: E402

BASE = os.environ.get("QC_AGENT_TEST_BASE_URL", "https://127.0.0.1:8444")
OUT = Path(__file__).parent / "p4-route-latency.json"


def review_client():
    """A logged-in ordinary-user client, from the review accounts file."""
    accts = json.load(open(os.environ["QC_REVIEW_ACCOUNTS"]))
    a = accts["qa_review"]
    c = new_client()
    r = c.post("/api/auth/login", json={"email_or_username": a["username"], "password": a["password"]})
    r.raise_for_status()
    return c


def timed(client: httpx.Client, method: str, path: str, n: int = 30, **kw):
    ts = []
    codes = set()
    for _ in range(n):
        t = time.perf_counter()
        r = client.request(method, path, **kw)
        ts.append((time.perf_counter() - t) * 1000)
        codes.add(r.status_code)
    ts.sort()
    return {
        "path": f"{method} {path}", "n": n, "codes": sorted(codes),
        "p50_ms": round(statistics.median(ts), 1),
        "p95_ms": round(ts[int(0.95 * (n - 1))], 1),
        "min_ms": round(ts[0], 1), "max_ms": round(ts[-1], 1),
    }


def main():
    admin = admin_client()
    user = review_client()

    # Record the size the measurement was taken at -- the numbers mean nothing
    # without it (explain-every-figure).
    njobs = len(admin.get("/api/jobs").json())
    threads = user.get("/api/threads").json()
    threads = threads if isinstance(threads, list) else threads.get("threads", [])
    context = {"measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "commit": "ca7e0ff", "jobs_admin_sees": njobs, "threads_qa_review_has": len(threads)}

    rows = []
    # P4.2: the read routes a busy deployment leans on.
    rows.append(timed(user, "GET", "/api/jobs"))
    rows.append(timed(user, "GET", "/api/threads"))
    rows.append(timed(admin, "GET", "/api/jobs"))          # admin sees all -> larger
    rows.append(timed(admin, "GET", "/api/admin/users"))
    rows.append(timed(admin, "GET", "/api/admin/activity"))  # R-045: walks every status.json
    rows.append(timed(admin, "GET", "/api/admin/storage"))   # R-046-ish: storage walk
    rows.append(timed(user, "GET", "/api/plots"))
    rows.append(timed(user, "GET", "/api/projects"))
    # P4.3: the hot polled route, on the biggest thread available.
    if threads:
        tid = threads[0].get("id") or threads[0].get("thread_id")
        rows.append(timed(user, "GET", f"/api/threads/{tid}/state", n=40))
        rows.append(timed(user, "GET", f"/api/threads/{tid}/jobs", n=40))

    OUT.write_text(json.dumps({"context": context, "rows": rows}, indent=2))
    print(json.dumps(context, indent=2))
    print()
    for r in rows:
        print(f"  {r['path']:44} p50 {r['p50_ms']:7} ms   p95 {r['p95_ms']:7} ms   (n={r['n']}, {r['codes']})")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
