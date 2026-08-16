"""PERF-01: baseline concurrent-login latency. Not a pass/fail gate --
this produces the numbers that decide whether Tier C's argon2-retuning
recommendation is actually justified (don't retune blind).

Since app/auth/rate_limit.py landed (SEC-03), every login in this burst
shares one apparent client IP (localhost behind nginx) and therefore one
rate-limit bucket -- unlike a real deployment, where this many concurrent
logins would almost always come from that many different real client IPs,
each with its own budget. So N_CONCURRENT > the configured per-IP budget
is now EXPECTED to produce a mix of successful and 429'd requests; this is
the rate limiter correctly doing its job, not a regression. Latency stats
are computed only over the non-429 subset (what actually reached argon2),
with the throttled count reported separately.
"""
from __future__ import annotations

import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, new_client, register, reset_rate_limits, summary  # noqa: E402

N_CONCURRENT = 30


def _login(username: str, password: str, correct: bool):
    c = new_client()
    start = time.perf_counter()
    r = c.post("/api/auth/login", json={"email_or_username": username, "password": password if correct else "wrong"})
    return (time.perf_counter() - start) * 1000.0, r.status_code


def main() -> None:
    reset_rate_limits()
    admin = admin_client()
    token = mint_invite(admin)
    password = "correct horse battery staple 1"
    _c, user = register(token, password=password)

    reset_rate_limits()
    with ThreadPoolExecutor(max_workers=N_CONCURRENT) as pool:
        futs = [pool.submit(_login, user["username"], password, i % 3 == 0) for i in range(N_CONCURRENT)]
        results = [f.result() for f in futs]

    throttled = [r for r in results if r[1] == 429]
    served = [r for r in results if r[1] != 429]
    latencies = sorted(r[0] for r in served)
    print(f"{N_CONCURRENT} concurrent logins (mix of correct/incorrect passwords):")
    if latencies:
        p50 = statistics.median(latencies)
        p95 = latencies[int(0.95 * len(latencies)) - 1]
        print(f"  served (non-429): {len(served)}   p50: {p50:.1f} ms   p95: {p95:.1f} ms   max: {latencies[-1]:.1f} ms")
    print(f"  throttled (429, correctly rate-limited): {len(throttled)}")
    print(f"  status codes: {sorted(set(r[1] for r in results))}")
    check("every concurrent login got a well-formed response (200, 401, or 429 -- never a server error)", all(r[1] in (200, 401, 429) for r in results))

    cleanup_user(admin, user["id"])
    reset_rate_limits()
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
