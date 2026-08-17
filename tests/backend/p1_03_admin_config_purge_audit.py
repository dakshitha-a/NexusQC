"""P1 functional coverage: admin config allowlist, concurrent-job-cap
clamping, purge audit-log entries, and admin_audit_log's DB-level
immutability (UPDATE/DELETE/TRUNCATE must raise)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, summary  # noqa: E402

COMPOSE_DIR = Path(__file__).resolve().parent.parent.parent


def _exec_api(code: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def main() -> None:
    admin = admin_client()

    # --- Config allowlist ---
    r_bad_key = admin.patch("/api/admin/config", json={"key": "not_a_real_config_key", "value": 123})
    check("PATCH with a non-allowlisted key is rejected", r_bad_key.status_code == 400, str(r_bad_key.status_code))

    r_negative = admin.patch("/api/admin/config", json={"key": "per_user_kb_quota_bytes", "value": -5})
    check("PATCH with a non-positive quota value is rejected", r_negative.status_code == 400, str(r_negative.status_code))

    r_cfg = admin.get("/api/admin/config")
    pool_size = r_cfg.json()["max_concurrent_jobs_pool_size"]
    r_over_ceiling = admin.patch("/api/admin/config", json={"key": "max_concurrent_jobs_total", "value": pool_size + 100})
    check(
        f"max_concurrent_jobs_total cannot exceed the fixed pool size ({pool_size})",
        r_over_ceiling.status_code == 400,
        str(r_over_ceiling.status_code),
    )

    r_valid = admin.patch("/api/admin/config", json={"key": "max_concurrent_jobs_per_user", "value": 3})
    check("a valid, in-range config PATCH succeeds", r_valid.status_code == 200, f"{r_valid.status_code} {r_valid.text[:150]}")

    # --- Purge produces an audit entry ---
    # Identity of the newest row, NOT a row count. GET /api/admin/audit-log
    # is capped at models.list_audit_log()'s limit of 500, and the table is
    # append-only, so on any deployment that has been used for a while the
    # count is pinned at 500 and "after > before" can never be true again --
    # which is exactly how this check started failing, long after the
    # behaviour it guards was still working fine.
    r_before = admin.get("/api/admin/audit-log")
    rows_before = r_before.json()
    newest_id_before = rows_before[0]["id"] if rows_before else None

    r_purge = admin.post("/api/admin/purge/jobs")
    check("purge/jobs succeeds", r_purge.status_code == 200, str(r_purge.status_code))

    rows_after = admin.get("/api/admin/audit-log").json()
    newest_id_after = rows_after[0]["id"] if rows_after else None
    check(
        "purge/jobs adds a new audit-log entry",
        newest_id_after is not None and newest_id_after != newest_id_before,
        f"newest id before={newest_id_before} after={newest_id_after}",
    )
    latest_action = rows_after[0]["action"] if rows_after else None
    check(
        "the newest audit-log entry records the purge",
        latest_action == "purge_all_jobs",
        str(latest_action),
    )

    # --- Audit log immutability (direct DB attempt, bypassing the app entirely) ---
    rc, out, err = _exec_api(
        "from app.auth.db import get_pool\n"
        "try:\n"
        "    with get_pool().connection() as conn:\n"
        "        conn.execute(\"UPDATE admin_audit_log SET action = 'tampered' WHERE true\")\n"
        "    print('UPDATE SUCCEEDED (bug)')\n"
        "except Exception as e:\n"
        "    print(f'UPDATE BLOCKED: {type(e).__name__}: {e}')"
    )
    print(out)
    check("a direct UPDATE against admin_audit_log is blocked by the DB trigger", "UPDATE BLOCKED" in out, out[:300])

    rc2, out2, err2 = _exec_api(
        "from app.auth.db import get_pool\n"
        "try:\n"
        "    with get_pool().connection() as conn:\n"
        "        conn.execute(\"DELETE FROM admin_audit_log\")\n"
        "    print('DELETE SUCCEEDED (bug)')\n"
        "except Exception as e:\n"
        "    print(f'DELETE BLOCKED: {type(e).__name__}: {e}')"
    )
    print(out2)
    check("a direct DELETE against admin_audit_log is blocked by the DB trigger", "DELETE BLOCKED" in out2, out2[:300])

    rc3, out3, err3 = _exec_api(
        "from app.auth.db import get_pool\n"
        "try:\n"
        "    with get_pool().connection() as conn:\n"
        "        conn.execute(\"TRUNCATE admin_audit_log\")\n"
        "    print('TRUNCATE SUCCEEDED (bug)')\n"
        "except Exception as e:\n"
        "    print(f'TRUNCATE BLOCKED: {type(e).__name__}: {e}')"
    )
    print(out3)
    check("a direct TRUNCATE against admin_audit_log is blocked by the DB trigger", "TRUNCATE BLOCKED" in out3, out3[:300])

    summary()


if __name__ == "__main__":
    main()
