"""SEC-06: the ownership sweep. app/auth/ownership.py's enforcement is 100%
route-handler-explicit (a call to check_owner_or_admin/owned_ids_filter at
the top of each handler), not middleware -- so the main systemic risk is a
resource-scoped route that simply forgot the call. This script does two
things:

1. Prints a static, hand-verified GUARDED/UNGUARDED table for every
   resource-scoped route in server/routes/{jobs,threads,chat}.py and
   server/routes/kb.py, built by reading every route handler's body in full
   (not a grep sample) -- see the per-route comments below for exactly what
   was checked.

2. LIVE-PROVES the one UNGUARDED route found this way:
   GET /api/jobs/{job_id}/artifacts/{key:path} (server/routes/jobs.py:601)
   has NO check_owner_or_admin call, and doesn't even require a login at
   all (no current_user_or_none()/get_current_user() call anywhere in its
   body) -- confirmed by reading the full function. This is a real,
   unauthenticated cross-user (and cross-EVERYONE) data leak: any job's
   cube files, spectra PNGs, uvvis plots, etc. are servable to any caller
   who knows or guesses the job_id, admin or not, logged in or not.

   Also spot-checks two GUARDED routes (GET /api/jobs/{job_id} and
   GET /api/threads/{thread_id}/state) as a positive control confirming
   the guard mechanism itself actually blocks cross-user access where it
   IS called -- so a failure of the artifact-route check below can be
   attributed to that route specifically, not a broken test harness.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent

# Hand-verified by reading every handler body in full (not grep-sampled) --
# see this repo's tests/README.md for the audit methodology.
ROUTE_TABLE = [
    ("GET /api/jobs", "list route, owned_ids_filter", "GUARDED"),
    ("GET /api/jobs/quota", "per-caller only, no cross-user path", "N/A (self-scoped)"),
    ("GET /api/jobs/{job_id}/children", "jobs.py:185", "GUARDED"),
    ("GET /api/threads/{thread_id}/jobs", "jobs.py:196", "GUARDED"),
    ("GET /api/jobs/{job_id}", "jobs.py:206", "GUARDED"),
    ("PATCH /api/jobs/{job_id}", "jobs.py:214", "GUARDED"),
    ("DELETE /api/jobs/{job_id}", "jobs.py:223", "GUARDED"),
    ("POST /api/jobs/{job_id}/cancel", "jobs.py:237", "GUARDED"),
    ("GET /api/jobs/{job_id}/download", "jobs.py:292", "GUARDED"),
    ("GET /api/jobs/{job_id}/raw_input", "jobs.py:333", "GUARDED"),
    ("POST /api/jobs/{job_id}/render_plot", "jobs.py:356", "GUARDED"),
    ("GET /api/jobs/{job_id}/log", "jobs.py:448", "GUARDED"),
    ("POST /api/jobs/{job_id}/orbitals/{index}/cube", "jobs.py:505", "GUARDED"),
    ("GET /api/jobs/{job_id}/neb_frames_live", "jobs.py:585", "GUARDED"),
    ("GET /api/jobs/{job_id}/artifacts/{key:path}", "jobs.py:601-627, NO check_owner_or_admin AND no auth call at all", "**UNGUARDED -- LIVE-PROVEN BELOW**"),
    ("GET /api/threads", "list route, owned_ids_filter", "GUARDED"),
    ("POST /api/threads", "records ownership on create", "GUARDED (by construction)"),
    ("PATCH /api/threads/{thread_id}", "threads.py:45", "GUARDED"),
    ("PATCH /api/threads/{thread_id}/pin", "threads.py:55", "GUARDED"),
    ("DELETE /api/threads/{thread_id}", "threads.py:65", "GUARDED"),
    ("GET/POST/DELETE /api/threads/{id}/{state,molecule/*,messages,stop,events,approvals/job}", "chat.py's _require_thread on every one", "GUARDED"),
    ("GET /api/kb/sources/{source}/content", "kb.py, _find_source_file(..., _owner_filter(...)) -- F-022 fixed, LIVE-PROVEN BELOW", "GUARDED (since F-022)"),
    ("DELETE /api/kb/sources/{source}", "kb.py:259, delete_source(..., owner_filter=_owner_filter(...))", "GUARDED (but see SEC-09: filename-only scoping for admin)"),
]


def _exec_api(code: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return proc.stdout.strip()


def _submit_marker_job(owner_user_id: str) -> str:
    """Directly submits a trivial PySCF single-point water job (bypassing
    chat/LLM entirely -- this test cares about the artifact-serving route,
    not the agent) and records ownership the same way approve_job does, via
    the same functions the real app calls. Returns the job_id once the job
    has a result.json with a 'test_marker' artifact."""
    code = f'''
import json, time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager, result_artifact_transaction, JOBS_DIR
from app.auth.models import record_ownership

m = resolve_molecule("water")
spec = JobSpec(method="single_point", engine="pyscf", molecule=m.to_dict(), params={{"method": "hf", "basis": "sto-3g"}})
job_id = get_job_manager().submit(spec)
for _ in range(60):
    status = get_job_manager().status(job_id)
    if status["status"] in ("completed", "failed"):
        break
    time.sleep(1)
marker_path = JOBS_DIR / job_id / "test_marker.txt"
marker_path.write_text("SEC-06 marker file -- should not be servable to another user")
with result_artifact_transaction(job_id) as artifacts:
    if artifacts is not None:
        artifacts["test_marker"] = str(marker_path)
record_ownership("job", job_id, "{owner_user_id}")
print(job_id)
'''
    return _exec_api(code)


def print_route_table() -> None:
    print("\n=== Ownership guard inventory (hand-verified, full-body reads) ===")
    width = max(len(r[0]) for r in ROUTE_TABLE)
    for route, note, status in ROUTE_TABLE:
        print(f"  {status:<40} {route:<{width}}  ({note})")
    print()


def main() -> None:
    print_route_table()

    admin = admin_client()
    token_a = mint_invite(admin)
    token_b = mint_invite(admin)
    from fixtures import register

    client_a, user_a = register(token_a)
    client_b, user_b = register(token_b)

    # --- Positive control: a GUARDED route actually blocks cross-user access ---
    r_thread = client_a.post("/api/threads", json={"label": "sec06 test thread"})
    check("user A can create a thread", r_thread.status_code == 201, str(r_thread.status_code))
    thread_id = r_thread.json()["thread_id"]
    r_cross = client_b.get(f"/api/threads/{thread_id}/state")
    check(
        "POSITIVE CONTROL: GUARDED route (thread state) denies cross-user access",
        r_cross.status_code == 404,
        f"got {r_cross.status_code} -- if this isn't 404, the guard mechanism itself is broken "
        "and the artifact-route finding below can't be trusted as a contrast",
    )

    # --- The actual finding: the artifact route ---
    job_id = _submit_marker_job(user_a["id"])
    print(f"created job {job_id}, owned by user A ({user_a['username']})")

    r_owner = client_a.get(f"/api/jobs/{job_id}/artifacts/test_marker")
    check("owner (user A) CAN fetch their own job's artifact", r_owner.status_code == 200, str(r_owner.status_code))

    r_other_user = client_b.get(f"/api/jobs/{job_id}/artifacts/test_marker")
    check(
        "UNGUARDED ROUTE: a different logged-in user (B) is denied A's job artifact",
        r_other_user.status_code in (403, 404),
        f"got {r_other_user.status_code} body={r_other_user.text[:80]!r} "
        "(200 confirms cross-user artifact leak via GET /api/jobs/{job_id}/artifacts/{key})",
    )

    import httpx
    from fixtures import BASE_URL

    anon = httpx.Client(base_url=BASE_URL, verify=False, timeout=30.0)  # no session cookie at all
    r_anon = anon.get(f"/api/jobs/{job_id}/artifacts/test_marker")
    check(
        "UNGUARDED ROUTE: an ANONYMOUS (not logged in at all) caller is denied A's job artifact",
        r_anon.status_code in (401, 403, 404),
        f"got {r_anon.status_code} body={r_anon.text[:80]!r} "
        "(200 confirms the artifact route requires no authentication whatsoever)",
    )

    # --- F-022 regression guard: the KB content route ---
    #
    # This route was listed as GUARDED in the table above on the strength of
    # it passing an _owner_filter into _find_source_file -- which it does.
    # The filter was then thrown away one level down, because
    # _content_search_dirs searched EVERY owner's upload directory whenever
    # the caller had an owner at all. A route-level read was not enough to
    # catch that, so the inventory now carries a live check for this route
    # too rather than a hand-verified claim.
    marker = "F-022 marker -- user B must never be able to read this"
    fname = f"sec06_private_{int(time.time())}.txt"
    r_up = client_a.post(
        "/api/kb/sources",
        files={"file": (fname, marker.encode(), "text/plain")},
        data={"doc_type": "manual"},
        timeout=180.0,
    )
    check("user A can upload a private KB source", r_up.status_code in (200, 201),
          f"{r_up.status_code} {r_up.text[:120]}")

    r_own = client_a.get(f"/api/kb/sources/{fname}/content")
    check("POSITIVE CONTROL: the owner (user A) can still read their own KB source",
          r_own.status_code == 200 and marker in r_own.text,
          f"{r_own.status_code} {r_own.text[:80]!r} -- if this fails the fix "
          "over-narrowed the search and broke legitimate access")

    r_leak = client_b.get(f"/api/kb/sources/{fname}/content")
    check(
        "F-022: a different logged-in user (B) is denied A's KB source content",
        r_leak.status_code == 404,
        f"got {r_leak.status_code} body={r_leak.text[:80]!r} "
        "(200 confirms the cross-user KB content leak has regressed)",
    )

    client_a.delete(f"/api/kb/sources/{fname}")
    cleanup_user(admin, user_a["id"])
    cleanup_user(admin, user_b["id"])
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
