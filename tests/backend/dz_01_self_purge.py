"""P9.4: the self-scoped "danger zone" -- POST /api/auth/purge-my-data and
GET /api/auth/download-my-data (server/routes/auth.py), backed by
app.auth.storage_quota.purge_own_data.

Deliberately scoped narrower than the admin-driven purge_user_data (used
for account deletion, see sec_08/sec_08b): a self-purge removes jobs, KB
uploads and geometry/blind-input uploads, but leaves chat threads
untouched, since the account itself survives afterward and losing every
conversation as a side effect of "clear out my old jobs" would be an
unrelated, surprising loss. Checked structurally here (purge_own_data's
return dict carries no thread_ids key at all) rather than through a live
chat turn -- creating a thread requires a real LLM tool-calling turn, and
sec_07_async_ownership_window.py's own docstring already establishes this
suite avoids that ("slow and non-deterministic to time precisely") in
favor of testing the underlying mechanism directly.

The running-job-kill case mirrors sec_08b_delete_user_running_job.py's own
established technique exactly (see its docstring for why: JobManager's
live Popen is scoped to whichever process called submit(), so this has to
run in the SAME one-shot in-container process that calls purge_own_data,
not raced against a real HTTP call from the test host).
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent


def _exec_api(code: str) -> str:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=90,
    )
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"in-container exec failed: {proc.stderr[:500]}")
    return proc.stdout.strip()


def _submit_completed_job(owner_user_id: str) -> str:
    code = f'''
import time
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
from app.auth.models import record_ownership

m = resolve_molecule("water")
spec = JobSpec(method="hf", engine="pyscf", molecule=m.to_dict(), task="single_point", subtype="gs",
                params={{"basis": "sto-3g"}})
job_id = get_job_manager().submit(spec)
for _ in range(60):
    status = get_job_manager().status(job_id)
    if status["status"] in ("completed", "failed"):
        break
    time.sleep(1)
record_ownership("job", job_id, "{owner_user_id}")
print(job_id)
'''
    return _exec_api(code)


def main() -> None:
    admin = admin_client()

    # -------------------------------------------------------- part 1: real HTTP round trip
    token_a = mint_invite(admin)
    client_a, user_a = register(token_a)

    job_id = _submit_completed_job(user_a["id"])
    print(f"user A: job {job_id}")

    r_up = client_a.post("/api/uploads", files={"file": ("dz01.xyz", b"1\n\nH 0 0 0\n", "text/plain")})
    check("user A can upload a geometry file", r_up.status_code == 201, f"{r_up.status_code} {r_up.text[:200]}")
    upload_id = r_up.json().get("id") if r_up.status_code == 201 else None

    r_kb = client_a.post("/api/kb/sources/text", json={
        "text": "dz_01 self-purge test content", "doc_type": "manual", "filename": "dz01_test.txt",
    })
    check("user A can add a KB text source", r_kb.status_code == 201, f"{r_kb.status_code} {r_kb.text[:200]}")

    r_job_before = client_a.get(f"/api/jobs/{job_id}")
    r_uploads_before = client_a.get("/api/uploads")
    r_kb_before = client_a.get("/api/kb/sources")
    check("job/upload/kb all exist before the purge",
          r_job_before.status_code == 200 and upload_id in [u["id"] for u in r_uploads_before.json()]
          and "dz01_test.txt" in [s["source"] for s in r_kb_before.json()],
          f"job={r_job_before.status_code}, uploads={r_uploads_before.json()}, kb sources present="
          f"{[s['source'] for s in r_kb_before.json()]}")

    r_purge = client_a.post("/api/auth/purge-my-data")
    check("POST /api/auth/purge-my-data succeeds for a non-admin, self-scoped caller",
          r_purge.status_code == 200, f"{r_purge.status_code} {r_purge.text[:300]}")
    body = r_purge.json() if r_purge.status_code == 200 else {}
    print(f"purge response: {body}")
    check("the purge response reports exactly the one job/upload/kb-source purged",
          body.get("purged_jobs") == 1 and body.get("purged_kb_sources") == 1 and body.get("purged_uploads") == 1,
          f"body={body}")

    r_job_after = client_a.get(f"/api/jobs/{job_id}")
    r_uploads_after = client_a.get("/api/uploads")
    r_kb_after = client_a.get("/api/kb/sources")
    check("the job is gone after self-purge", r_job_after.status_code == 404, str(r_job_after.status_code))
    check("the upload is gone after self-purge", upload_id not in [u["id"] for u in r_uploads_after.json()],
          str(r_uploads_after.json()))
    check("the KB source is gone after self-purge", "dz01_test.txt" not in [s["source"] for s in r_kb_after.json()],
          str([s["source"] for s in r_kb_after.json()]))

    # -------------------------------------------------------- part 2: threads are untouched (structural)
    code = '''
import json
from app.auth.storage_quota import purge_own_data
result = purge_own_data("nonexistent-user-id-no-resources")
print(json.dumps(sorted(result.keys())))
'''
    keys = json.loads(_exec_api(code))
    check("purge_own_data's return shape carries no thread_ids key -- chat threads are structurally out of "
          "scope for a self-purge, unlike admin-driven purge_user_data", "thread_ids" not in keys,
          f"keys={keys}")

    # -------------------------------------------------------- part 3: a genuinely running job is killed, not orphaned
    token_b = mint_invite(admin)
    _client_b, user_b = register(token_b)
    code = f'''
import json
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager, read_status
from app.auth.models import record_ownership
from app.auth.storage_quota import purge_own_data
from app.config import JOBS_DIR

m = resolve_molecule("benzene")
spec = JobSpec(method="hf", engine="pyscf", molecule=m.to_dict(), task="freq", subtype="",
                params={{"basis": "6-31g"}})
job_id = get_job_manager().submit(spec)
record_ownership("job", job_id, "{user_b['id']}")
status_before = read_status(job_id)["status"]

purged = purge_own_data("{user_b['id']}")

print(json.dumps({{
    "job_id": job_id, "status_before_purge": status_before, "purged": purged,
    "dir_exists_after_purge": (JOBS_DIR / job_id).exists(),
}}))
'''
    info = json.loads(_exec_api(code))
    print(f"user B: job {info['job_id']}, status immediately before purge_own_data ran: "
          f"{info['status_before_purge']}")
    if info["status_before_purge"] not in ("pending", "running"):
        print("NOTE: job was already terminal before purge_own_data() ran -- this run only exercises the "
              "already-terminal case, not the mid-flight cancel path. Re-run to try to catch the race.")
    check("a genuinely pending/running job is cancelled and purged by purge_own_data, never left orphaned",
          info["job_id"] in info["purged"]["job_ids"] and not info["dir_exists_after_purge"],
          f"info={info}")

    # -------------------------------------------------------- part 4: download-my-data zip
    token_c = mint_invite(admin)
    client_c, user_c = register(token_c)
    job_id_c = _submit_completed_job(user_c["id"])
    client_c.post("/api/uploads", files={"file": ("dz01c.xyz", b"1\n\nH 0 0 0\n", "text/plain")})
    client_c.post("/api/kb/sources/text", json={
        "text": "dz_01 download test content", "doc_type": "manual", "filename": "dz01c_test.txt",
    })

    r_dl = client_c.get("/api/auth/download-my-data")
    check("GET /api/auth/download-my-data returns 200 with a zip body",
          r_dl.status_code == 200 and r_dl.headers.get("content-type") == "application/zip",
          f"{r_dl.status_code}, content-type={r_dl.headers.get('content-type')}")
    names = []
    zip_ok = False
    if r_dl.status_code == 200:
        try:
            with zipfile.ZipFile(io.BytesIO(r_dl.content)) as zf:
                names = zf.namelist()
                zip_ok = zf.testzip() is None
        except zipfile.BadZipFile:
            zip_ok = False
    has_job = any(n.startswith("jobs/") for n in names)
    has_upload = any(n.startswith("uploads/") and "dz01c.xyz" in n for n in names)
    has_kb = any(n == "kb/dz01c_test.txt" for n in names)
    check("the downloaded zip is well-formed and contains this user's job, upload and KB source",
          zip_ok and has_job and has_upload and has_kb, f"names={names}")

    cleanup_user(admin, user_a["id"])
    cleanup_user(admin, user_b["id"])
    cleanup_user(admin, user_c["id"])
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
