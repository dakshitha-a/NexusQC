"""Authorization sweep across EVERY route the app actually exposes.

The route inventory is not hand-written -- it is pulled from FastAPI's own
/openapi.json (fetched from inside the api container, since nginx only
proxies /api/* and would serve the SPA fallback for it). That way a route
added later cannot silently escape this sweep, which is the whole point:
SEC-06 was GET /api/jobs/{job_id}/artifacts/{key:path} shipping with NO
ownership check and NO auth requirement at all, anonymously reachable for
any job's artifacts. It was the single most severe finding of that pass,
and a hand-maintained list is exactly how a route goes unnoticed.

Three passes over the same inventory:
  1. ANONYMOUS  -- no cookie at all. Everything except the documented
     public routes must reject.
  2. NON-ADMIN  -- an ordinary user against every /api/admin/* route.
     Must be 403.
  3. CROSS-USER -- user B against user A's real resources. Must be 404,
     not 403 (XN-10: deliberate, does not leak existence).

Read-only: every request is a GET, or a state-changing method sent with a
deliberately invalid/absent body so that a route which SHOULD reject on
auth never gets far enough to mutate anything. Any route that returns 2xx
to an anonymous caller is reported with its status, not silently skipped.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client, check, cleanup_user, mint_invite, new_client, register, summary,
)

REPO = Path(__file__).resolve().parent.parent.parent

# Routes that are legitimately reachable with no session at all.
#
# /api/version and /api/health/deep are here for the same documented reason
# /api/health is: server/main.py puts all three outside the `if DATABASE_URL`
# block because they have to answer while the deployment is in exactly the
# state that makes authentication impossible -- the updater polls them and the
# browser needs to know when to reload. Omitting /api/version made this
# script report a false regression on every run and turned the whole e2e
# suite's verdict from one failure into two (R-100).
PUBLIC_ROUTES = {
    ("GET", "/api/health"),
    ("GET", "/api/health/deep"),
    ("GET", "/api/version"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/register"),
}

# Path-param fillers so a route is actually exercised rather than 404ing
# on a malformed path before auth is ever consulted.
FILLERS = {
    "thread_id": "e2e-nonexistent-thread",
    "job_id": "0123456789ab",
    "source": "e2e-nonexistent-source.txt",
    "user_id": "00000000-0000-0000-0000-000000000000",
    "report_id": "1",
    "index": "1",
    "key": "raw_output",
    "frame_id": "e2e-nonexistent-frame",
}


def fetch_openapi() -> dict:
    p = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c",
         "import json,urllib.request;"
         "print(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json').read().decode())"],
        cwd=str(REPO), capture_output=True, text=True, timeout=60,
    )
    if p.returncode != 0:
        raise RuntimeError(f"could not fetch openapi.json: {p.stderr[:400]}")
    return json.loads(p.stdout)


def concrete(path: str) -> str:
    out = path
    for name, val in FILLERS.items():
        out = out.replace("{" + name + "}", val).replace("{" + name + ":path}", val)
    return out


def routes(spec: dict) -> list[tuple[str, str, str]]:
    """[(METHOD, template_path, concrete_path)] for every /api/ route."""
    out = []
    for tmpl, ops in spec.get("paths", {}).items():
        if not tmpl.startswith("/api/"):
            continue
        for method in ops:
            if method.upper() in ("GET", "POST", "PATCH", "DELETE", "PUT"):
                out.append((method.upper(), tmpl, concrete(tmpl)))
    return sorted(out)


# Minimal VALID bodies per route template. This matters: FastAPI validates
# the request body BEFORE the handler runs, so an empty {} on a route whose
# schema has required fields returns 422 without ever reaching the
# ownership check -- which would make a cross-user probe look like a
# missing guard when the guard is fine. (Confirmed: with valid bodies every
# cross-user route returns 404, identical to a nonexistent thread, so
# there is no existence leak.)
VALID_BODIES = {
    "/api/threads": {"label": "e2e-probe"},
    "/api/threads/{thread_id}": {"label": "e2e-probe"},
    "/api/threads/{thread_id}/pin": {"pinned": True},
    "/api/threads/{thread_id}/messages": {"text": "e2e", "job_ids": [], "frame_id": None},
    "/api/threads/{thread_id}/approvals/job": {"approved": False},
    "/api/threads/{thread_id}/molecule/build": {"molblock": "", "charge": 0, "multiplicity": 1},
    "/api/jobs/{job_id}": {"label": "e2e-probe"},
    "/api/jobs/{job_id}/render_plot": {"kind": "optimization_energy"},
    "/api/auth/login": {"email_or_username": "e2e-nobody", "password": "x" * 12},
    "/api/auth/register": {"invite_token": "e2e-bogus", "email": "e2e@example.test",
                           "username": "e2eprobe", "password": "x" * 12,
                           "first_name": "E2E", "last_name": "Probe"},
    "/api/auth/change-password": {"current_password": "x" * 12, "new_password": "y" * 12},
    "/api/bug-reports": {"body": "e2e probe"},
    "/api/admin/config": {"key": "per_user_kb_quota_bytes", "value": 1},
    "/api/admin/invites": {"role": "user", "ttl_hours": 1},
    "/api/admin/purge/threads": {},
    "/api/admin/bug-reports/{report_id}": {"status": "open"},
}


def call(client, method: str, path: str, tmpl: str = ""):
    kw = {"timeout": 30.0}
    if method in ("POST", "PATCH", "PUT"):
        kw["json"] = VALID_BODIES.get(tmpl, {})
    try:
        return client.request(method, path, **kw)
    except Exception as e:
        return type("R", (), {"status_code": -1, "text": str(e)})()


def main() -> None:
    admin = admin_client()
    spec = fetch_openapi()
    all_routes = routes(spec)
    print(f"Discovered {len(all_routes)} /api/ routes from the app's own OpenAPI schema.\n")

    # ---------------------------------------------------------------- pass 1
    print("--- Pass 1: ANONYMOUS (no cookie) ---")
    anon = new_client()
    leaks = []
    for method, tmpl, path in all_routes:
        if (method, tmpl) in PUBLIC_ROUTES:
            continue
        r = call(anon, method, path, tmpl)
        # 401 = unauthenticated (correct). 403 = CSRF/origin or admin gate
        # (also a rejection). 404/405/422 are acceptable only if they come
        # from a route that never reached its handler body; 2xx never is.
        ok = r.status_code not in range(200, 300)
        if not ok:
            leaks.append(f"{method} {tmpl} -> {r.status_code}")
    check(
        f"anonymous caller is rejected by all {len(all_routes) - len(PUBLIC_ROUTES)} non-public routes",
        not leaks, "; ".join(leaks) if leaks else "",
    )
    for line in leaks:
        print(f"    [LEAK] {line}")

    # public routes really are reachable
    for method, tmpl in sorted(PUBLIC_ROUTES):
        r = call(anon, method, concrete(tmpl), tmpl)
        check(f"public route {method} {tmpl} reachable anonymously",
              r.status_code != 404, str(r.status_code))

    # ---------------------------------------------------------------- pass 2
    print("\n--- Pass 2: NON-ADMIN against /api/admin/* ---")
    tok = mint_invite(admin, "user")
    ua, ua_info = register(tok)
    admin_routes = [r for r in all_routes if r[1].startswith("/api/admin/")]
    bad = []
    for method, tmpl, path in admin_routes:
        r = call(ua, method, path, tmpl)
        if r.status_code != 403:
            bad.append(f"{method} {tmpl} -> {r.status_code} (want 403)")
    check(f"non-admin gets 403 on all {len(admin_routes)} /api/admin/* routes",
          not bad, "; ".join(bad))
    for line in bad:
        print(f"    [BAD] {line}")

    # ---------------------------------------------------------------- pass 3
    print("\n--- Pass 3: CROSS-USER isolation (expect 404, per XN-10) ---")
    tok_b = mint_invite(admin, "user")
    ub, ub_info = register(tok_b)

    # A creates a thread; B must not see or touch it.
    r = ua.post("/api/threads", json={"label": "e2e-isolation"})
    r.raise_for_status()
    tid = r.json()["thread_id"]

    probes = [
        ("GET", f"/api/threads/{tid}/state", ""),
        ("PATCH", f"/api/threads/{tid}", "/api/threads/{thread_id}"),
        ("DELETE", f"/api/threads/{tid}", ""),
        ("GET", f"/api/threads/{tid}/jobs", ""),
        ("POST", f"/api/threads/{tid}/messages", "/api/threads/{thread_id}/messages"),
        ("POST", f"/api/threads/{tid}/stop", ""),
        ("POST", f"/api/threads/{tid}/molecule/reset", ""),
        ("PATCH", f"/api/threads/{tid}/pin", "/api/threads/{thread_id}/pin"),
    ]
    wrong = []
    for method, path, tmpl in probes:
        r = call(ub, method, path, tmpl)
        if r.status_code != 404:
            wrong.append(f"{method} {path} -> {r.status_code} (want 404)")
    check("user B gets 404 on every one of user A's thread routes", not wrong, "; ".join(wrong))
    for line in wrong:
        print(f"    [BAD] {line}")

    # A's thread must not appear in B's listing.
    r = ub.get("/api/threads")
    ids = [t.get("thread_id") for t in (r.json() if r.status_code == 200 else [])]
    check("user A's thread is absent from user B's /api/threads listing", tid not in ids)

    # Cleanup
    ua.delete(f"/api/threads/{tid}")
    for info in (ua_info, ub_info):
        uid = (info.get("user") or info).get("id")
        if uid:
            cleanup_user(admin, uid)

    summary()


if __name__ == "__main__":
    main()
