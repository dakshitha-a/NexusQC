"""SEC-05: verify_login (app/auth/models.py) is written to return the same
None for "unknown user" and "known user, wrong password" -- explicitly to
avoid a login form distinguishing the two. But it only calls argon2's
verify_password (tens of ms of deliberately-expensive work) in the SECOND
case; the first case short-circuits on `user is None` with no hashing at
all. That's a textbook timing side-channel: an attacker can distinguish
"this username doesn't exist" from "this username exists" purely from
response latency, without ever seeing a different status code or message.

Measures median latency for N trials against a genuinely unknown username
vs. N trials against a real username with a wrong password. A large,
consistent delta confirms the oracle is real and measurable over the
network, not just theoretical.

Since app/auth/rate_limit.py (SEC-03) landed, /api/auth/login now 429s
after a handful of attempts from one IP, and it does so BEFORE
verify_login (and therefore before the argon2 call this test is trying to
measure) ever runs -- a 429 response is fast and near-constant-time
regardless of which branch would have been taken, which would flatten out
and mask a real timing oracle rather than revealing one. reset_rate_limits()
is therefore called before every single trial to isolate the mechanism
this test actually targets from the separate one added afterward.
N_TRIALS is lower than before the rate limiter existed, since each trial
now costs one extra docker-exec round trip.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, new_client, qatest_username, register, reset_rate_limits, summary  # noqa: E402

N_TRIALS = 15
# A delta below this is attributable to normal network/scheduling jitter;
# argon2's own hashing cost is typically tens of milliseconds, so a real
# oracle should show up far above this threshold.
THRESHOLD_MS = 20.0


def _time_login(username: str, password: str) -> float:
    reset_rate_limits()
    c = new_client()
    start = time.perf_counter()
    c.post("/api/auth/login", json={"email_or_username": username, "password": password})
    return (time.perf_counter() - start) * 1000.0


def main() -> None:
    admin = admin_client()
    token = mint_invite(admin)
    _reg_client, user = register(token, password="correct horse battery staple 1")

    unknown_times = [_time_login(f"{qatest_username()}_nonexistent", "irrelevant-password-1") for _ in range(N_TRIALS)]
    known_wrong_times = [_time_login(user["username"], "definitely-the-wrong-password-1") for _ in range(N_TRIALS)]

    med_unknown = statistics.median(unknown_times)
    med_known = statistics.median(known_wrong_times)
    delta = med_known - med_unknown
    print(f"median latency, unknown username:        {med_unknown:.2f} ms")
    print(f"median latency, known username/wrong pw:  {med_known:.2f} ms")
    print(f"delta:                                     {delta:.2f} ms  (threshold: {THRESHOLD_MS} ms)")

    check(
        "no measurable timing oracle between unknown-user and known-user-wrong-password",
        delta < THRESHOLD_MS,
        f"delta={delta:.2f}ms >= {THRESHOLD_MS}ms confirms a real user-enumeration timing side-channel "
        "(argon2 verification only runs in the known-user branch)",
    )

    cleanup_user(admin, user["id"])
    reset_rate_limits()
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
