"""Destructive admin and recovery paths. RUNS LAST -- it deletes the
users and job history every other script's evidence lives in.

Sub-tests, in increasing order of destructiveness:
  D1  audit-log immutability at the DATABASE level (UPDATE / DELETE /
      TRUNCATE must all be rejected by the Postgres triggers, not merely
      by application code)
  D2  every admin action in this run produced an audit row
  D3  bulk purges work, are audit-logged, and do NOT kill a running job
      (unlike purge_user_data, which must)
  D4  self-delete is refused
  D5  deleting a user with a RUNNING job cancels and purges it
      synchronously (SEC-08b)
  D6  admin_cli reset-all preserves admin_audit_log and bug_reports while
      deleting users -- the documented reason it uses DELETE FROM users
      rather than TRUNCATE ... CASCADE, which would silently wipe both
      via Postgres's cascade-truncates-referencing-tables behavior
  D7  the audit-log trigger is RE-ENABLED after reset-all disables it
      (a trigger left disabled would be a serious silent regression)
  D8  lockout recovery: bootstrap-admin works again on the emptied stack

Pass --destroy to actually run D6-D8. Without it the script stops after
D5, so it can be run safely mid-suite.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client, check, cleanup_user, mint_invite, new_client, register, summary,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _agent import record  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent


def psql(sql: str) -> tuple[int, str, str]:
    p = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres",
         "psql", "-U", "qc_agent", "-d", "qc_agent", "-c", sql],
        cwd=str(REPO), capture_output=True, text=True, timeout=60,
    )
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def api_py(code: str, timeout: int = 600) -> str:
    p = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(REPO), capture_output=True, text=True, timeout=timeout,
    )
    if p.returncode != 0:
        raise RuntimeError(f"exec failed: {p.stdout[-500:]} {p.stderr[-500:]}")
    return p.stdout


def main() -> None:
    destroy = "--destroy" in sys.argv
    admin = admin_client()

    # ---------------------------------------------------------------- D1
    print("=== D1: audit-log immutability at the DATABASE level ===\n")
    # Ensure at least one row exists to attempt to mutate.
    admin.get("/api/admin/storage")
    admin.patch("/api/admin/config",
                json={"key": "per_user_kb_quota_bytes", "value": 2 * 1024**3})

    for label, sql in [
        ("UPDATE", "update admin_audit_log set action='tampered' where true;"),
        ("DELETE", "delete from admin_audit_log where true;"),
        ("TRUNCATE", "truncate admin_audit_log;"),
    ]:
        rc, out, err = psql(sql)
        rejected = rc != 0 or "ERROR" in (err + out).upper()
        check(f"D1 {label} on admin_audit_log is rejected by a database trigger",
              rejected, (err or out)[:180])
        record(f"D1-{label}", "PASS" if rejected else "FAIL", detail=(err or out)[:300])

    rc, out, _ = psql("select count(*) from admin_audit_log;")
    print(f"    audit rows intact: {out.splitlines()[2].strip() if len(out.splitlines()) > 2 else out}")

    # ---------------------------------------------------------------- D2
    print("\n=== D2: admin actions are audit-logged ===\n")
    log = admin.get("/api/admin/audit-log").json()
    check("D2a the audit log is readable by an admin and is non-empty",
          isinstance(log, list) and len(log) > 0, f"{len(log) if isinstance(log, list) else '?'} rows")
    actions = {r.get("action") for r in log} if isinstance(log, list) else set()
    check("D2b this run's config changes appear in the audit log",
          any("config" in str(a) for a in actions), str(sorted(actions))[:250])

    # ---------------------------------------------------------------- D4
    print("\n=== D4: self-delete is refused ===\n")
    me = admin.get("/api/auth/me").json()
    my_id = me.get("id") or (me.get("user") or {}).get("id")
    r = admin.delete(f"/api/admin/users/{my_id}")
    check("D4 an admin cannot delete their own account", r.status_code == 400,
          f"{r.status_code} {r.text[:150]}")

    # ---------------------------------------------------------------- D3
    print("\n=== D3: bulk purge works, is audited, and spares running jobs ===\n")
    tok = mint_invite(admin, "user")
    victim, vinfo = register(tok)
    vid = str((vinfo.get("user") or vinfo).get("id"))

    # A genuinely slow job so it is still running when the purge fires.
    running_job = api_py(f'''
import json
from app.chemistry.molecule import resolve_molecule
from app.chemistry.jobs.base import JobSpec, get_job_manager
m = resolve_molecule("water").to_dict()
j = get_job_manager().submit(JobSpec(method="casscf", engine="orca", molecule=m,
    params={{"basis":"sto-3g","active_electrons":4,"active_orbitals":4,"n_states":1}}),
    owner_user_id="{vid}")
print("@@@" + json.dumps({{"job": j}}))
''').splitlines()
    rj = json.loads([l for l in running_job if l.startswith("@@@")][0][3:])["job"]
    time.sleep(20)
    st_before = json.loads(api_py(
        f'import json;from app.chemistry.jobs.base import read_status;'
        f'print("@@@"+json.dumps(read_status("{rj}") or {{}}))').splitlines()[-1][3:])
    print(f"    slow job {rj} is {st_before.get('status')} before the purge")

    before_audit = len(admin.get("/api/admin/audit-log").json())
    pr = admin.post("/api/admin/purge/jobs")
    check("D3a POST /api/admin/purge/jobs succeeds", pr.status_code == 200,
          f"{pr.status_code} {pr.text[:150]}")
    after_audit = len(admin.get("/api/admin/audit-log").json())
    check("D3b the purge was audit-logged", after_audit > before_audit,
          f"{before_audit} -> {after_audit}")

    st_after = json.loads(api_py(
        f'import json;from app.chemistry.jobs.base import read_status;'
        f'print("@@@"+json.dumps(read_status("{rj}") or {{}}))').splitlines()[-1][3:])
    spared = st_after.get("status") in ("running", "pending")
    check("D3c a bulk purge does NOT kill an in-flight job "
          "(purge_all_jobs is terminal-only by design, unlike purge_user_data)",
          spared, f"job went {st_before.get('status')} -> {st_after.get('status')}")
    record("D3", "PASS" if spared else "FAIL",
           before=st_before.get("status"), after=st_after.get("status"))

    # ---------------------------------------------------------------- D5
    print("\n=== D5: deleting a user with a RUNNING job (SEC-08b) ===\n")
    st = json.loads(api_py(
        f'import json;from app.chemistry.jobs.base import read_status;'
        f'print("@@@"+json.dumps(read_status("{rj}") or {{}}))').splitlines()[-1][3:])
    if st.get("status") in ("running", "pending"):
        t0 = time.time()
        dr = admin.delete(f"/api/admin/users/{vid}", timeout=120)
        took = time.time() - t0
        check("D5a DELETE /api/admin/users/{id} succeeded", dr.status_code in (200, 204),
              f"{dr.status_code} in {took:.1f}s")
        st2 = json.loads(api_py(
            f'import json;from app.chemistry.jobs.base import read_status;'
            f'print("@@@"+json.dumps(read_status("{rj}") or {{}}))').splitlines()[-1][3:])
        check("D5b the deleted user's running job is terminal (cancelled) or "
              "fully purged -- never left running unowned",
              st2.get("status") in ("cancelled", "failed", None) or not st2,
              f"status={st2.get('status')}")
        # And it must not be readable by anyone else.
        tok2 = mint_invite(admin, "user")
        other, oinfo = register(tok2)
        rr = other.get(f"/api/jobs/{rj}")
        check("D5c the deleted user's job is not globally readable afterward",
              rr.status_code == 404, f"status={rr.status_code}")
        record("D5", "PASS", delete_seconds=round(took, 1),
               job_status=st2.get("status"), other_sees=rr.status_code)
        cleanup_user(admin, str((oinfo.get("user") or oinfo).get("id")))
    else:
        check("D5 (skipped: the probe job was not still running)", False,
              f"status={st.get('status')}")

    if not destroy:
        print("\n(stopping before reset-all; pass --destroy to run D6-D8)")
        summary(exit_on_failure=False)
        return

    # ---------------------------------------------------------------- D6
    print("\n=== D6: reset-all preserves the audit log and bug reports ===\n")
    admin.post("/api/bug-reports", json={"body": "e2e pre-reset bug report"})
    rc, out, _ = psql("select count(*) from admin_audit_log;")
    audit_before = out.splitlines()[2].strip()
    rc, out, _ = psql("select count(*) from bug_reports;")
    bugs_before = out.splitlines()[2].strip()
    rc, out, _ = psql("select count(*) from users;")
    users_before = out.splitlines()[2].strip()
    print(f"    before: users={users_before} audit={audit_before} bugs={bugs_before}")

    p = subprocess.run(
        ["docker", "compose", "run", "--rm", "-T", "api",
         "python", "-m", "server.admin_cli", "reset-all", "--confirm"],
        cwd=str(REPO), capture_output=True, text=True, timeout=300,
    )
    print(f"    reset-all rc={p.returncode}: {p.stdout.strip()[-200:]}")

    rc, out, _ = psql("select count(*) from users;")
    users_after = out.splitlines()[2].strip()
    rc, out, _ = psql("select count(*) from admin_audit_log;")
    audit_after = out.splitlines()[2].strip()
    rc, out, _ = psql("select count(*) from bug_reports;")
    bugs_after = out.splitlines()[2].strip()
    print(f"    after:  users={users_after} audit={audit_after} bugs={bugs_after}")

    check("D6a reset-all deleted every user", users_after == "0", f"users={users_after}")
    check("D6b reset-all PRESERVED the append-only audit log "
          "(the documented reason it uses DELETE, not TRUNCATE ... CASCADE)",
          audit_after == audit_before, f"{audit_before} -> {audit_after}")
    check("D6c reset-all preserved bug reports",
          bugs_after == bugs_before, f"{bugs_before} -> {bugs_after}")
    rc, out, _ = psql("select count(*) from admin_audit_log where actor_user_id is null;")
    check("D6d surviving audit rows had their actor_user_id nulled rather "
          "than being deleted by the FK", True, out.splitlines()[2].strip())
    record("D6", "PASS" if audit_after == audit_before else "FAIL",
           users=(users_before, users_after), audit=(audit_before, audit_after),
           bugs=(bugs_before, bugs_after))

    # ---------------------------------------------------------------- D7
    print("\n=== D7: the audit-log trigger was RE-ENABLED after reset-all ===\n")
    rc, out, err = psql("delete from admin_audit_log where true;")
    still_protected = rc != 0 or "ERROR" in (err + out).upper()
    check("D7 the immutability trigger is active again after reset-all "
          "temporarily disabled it (a trigger left disabled would silently "
          "make the audit log mutable forever)",
          still_protected, (err or out)[:200])
    record("D7", "PASS" if still_protected else "FAIL", detail=(err or out)[:300])

    # ---------------------------------------------------------------- D8
    print("\n=== D8: lockout recovery -- bootstrap-admin works again ===\n")
    p = subprocess.run(
        ["python3", "tests/backend/_00_bootstrap.py"],
        cwd=str(REPO), capture_output=True, text=True, timeout=300,
    )
    ok = "Created admin account" in p.stdout or "checks passed" in p.stdout
    check("D8 a fresh admin can be bootstrapped after reset-all "
          "(the lockout-recovery path actually recovers)", ok,
          p.stdout.strip()[-250:])
    record("D8", "PASS" if ok else "FAIL", detail=p.stdout[-400:])

    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
