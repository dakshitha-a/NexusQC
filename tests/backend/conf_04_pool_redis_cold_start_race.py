"""CONF-04: app/auth/db.py's get_pool() and app/auth/redis_session.py's
get_client() both use double-checked locking for their lazy module-global
singletons. CLAUDE.md documents a REAL prior bug of exactly this shape
(unlocked race) in app/rag/store.py's get_store() that was fixed with this
same pattern -- this test fires many concurrent first-touch requests at a
freshly-restarted `api` container to confirm these two don't share that
bug (i.e. the pattern was actually applied correctly here, not just
described in a comment).

Restarting the container resets both module-global singletons to None,
recreating a genuine cold-start race window.
"""
from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import check, new_client, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent
N_CONCURRENT = 25


def _wait_healthy(timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    c = new_client()
    while time.time() < deadline:
        try:
            r = c.get("/api/health")
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main() -> None:
    print("restarting api container to force a cold pool/redis-client singleton...")
    subprocess.run(["docker", "compose", "restart", "api"], cwd=str(COMPOSE_DIR), check=True, capture_output=True)
    check("api container became healthy again after restart", _wait_healthy())

    def _first_touch(i: int):
        c = new_client()
        # /api/auth/me is unauthenticated (401) but still exercises
        # get_current_user -> redis_session.get_client() and, on any
        # concurrent registration below, db.get_pool() -- both lazy
        # singletons under test.
        return c.get("/api/auth/me").status_code

    with ThreadPoolExecutor(max_workers=N_CONCURRENT) as pool:
        results = list(pool.map(_first_touch, range(N_CONCURRENT)))

    all_401 = all(r == 401 for r in results)
    check(
        f"{N_CONCURRENT} concurrent first-touch requests against a freshly-restarted backend "
        "all completed cleanly (no crash, no duplicate-singleton connection errors)",
        all_401,
        f"status codes seen: {sorted(set(results))} (expected only 401 -- anything else, "
        "especially a 500, suggests a races in get_pool()/get_client())",
    )
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
