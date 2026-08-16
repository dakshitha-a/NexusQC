"""PERF-02: GET /api/admin/storage (server/routes/admin.py) is explicitly
uncached, walking disk+Postgres fresh on every call. Measures its
wall-clock cost at current (near-empty, freshly-provisioned test stack)
data volume. Not a pass/fail gate -- the number here decides whether the
Tier C "add a short TTL cache" recommendation is urgent or cosmetic; a
larger-scale repeat (seeding hundreds of jobs) is a natural follow-up once
this baseline exists, not attempted here since seeding real completed
jobs at that volume is itself a slow, heavy operation better run as a
deliberate one-off than baked into a routine test-suite run.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, summary  # noqa: E402

N_CALLS = 15


def main() -> None:
    admin = admin_client()
    times = []
    for _ in range(N_CALLS):
        start = time.perf_counter()
        r = admin.get("/api/admin/storage")
        times.append((time.perf_counter() - start) * 1000.0)
        check("GET /api/admin/storage returns 200", r.status_code == 200, str(r.status_code))

    print(f"GET /api/admin/storage latency over {N_CALLS} calls at current (near-empty) data volume:")
    print(f"  median: {statistics.median(times):.1f} ms   max: {max(times):.1f} ms")
    print(
        "\nBaseline only -- re-run this script after seeding a few hundred real jobs/KB sources to see "
        "how this scales before deciding whether the Tier C caching fix is urgent."
    )
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
