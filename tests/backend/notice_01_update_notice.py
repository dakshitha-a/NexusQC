"""The update notice: its route, its expiry, the deploy fields that feed it,
and the update.sh functions that write it.

Every user sees the notice, so this script never lets a live one appear.
Everything it writes into the update_notice row carries an expires_at
already in the past, which current_notice() treats as no notice at all, and
the row is deleted afterwards. It refuses to start if a notice row already
exists, because that means an update is running and the row is not ours.

  1. GET /api/notice answers without a session, with notice, maintenance
     and the server's clock, and /api/notice is on the maintenance exempt
     list (so the overlay can ask it during the lockout).
  2. current_notice(), with its read stubbed in-container: a notice due in
     the future comes back with every field the banner reads; one past its
     expires_at comes back as None.
  3. POST /api/admin/deploy refuses notice_minutes outside 0-120 and a
     message over 500 characters, before anything is written; cancelling
     when no update is announced is a 409.
  4. update.sh's post_notice, run from the script itself: it writes the
     phase, the restart time, the stops-running-jobs flag and a message with
     quotes and a backslash intact, and the api then serves no notice,
     because it had expired. cancel_requested answers yes only for its own
     notice id.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, new_client, shell_function, skip, summary  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent


def _exec_api(code: str) -> str:
    proc = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-c", code],
                          cwd=str(REPO), capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-600:])
    return proc.stdout.strip()


def _psql(sql: str) -> str:
    proc = subprocess.run(["docker", "compose", "exec", "-T", "postgres", "sh", "-c",
                           f'psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "{sql}"'],
                          cwd=str(REPO), capture_output=True, text=True, timeout=60)
    return proc.stdout.strip()


def main() -> None:
    if _psql("SELECT count(*) FROM app_config WHERE key IN ('update_notice','update_cancel')") not in ("", "0"):
        skip("the whole script", "an update notice already exists, so an update may be running; "
                                  "this script writes the same row and will not touch it")
        summary()
        return

    print("== 1. the route ==")
    r = new_client().get("/api/notice")
    body = r.json() if r.status_code == 200 else {}
    check("GET /api/notice answers without a session", r.status_code == 200, f"HTTP {r.status_code}")
    check("with notice, maintenance and the server clock",
          set(body) >= {"notice", "maintenance", "now"} and abs(body.get("now", 0) - time.time()) < 120,
          json.dumps(body)[:200])
    check("and no notice when no update is announced", body.get("notice") is None, str(body.get("notice")))
    exempt = _exec_api("from app.auth.middleware import _MAINTENANCE_EXEMPT; print('/api/notice' in _MAINTENANCE_EXEMPT)")
    check("/api/notice is exempt from maintenance mode", exempt.endswith("True"), exempt)

    print("\n== 2. current_notice ==")
    out = _exec_api('''
import json, time
from app.auth import update_notice as u
now = time.time()
u._read = lambda: {"id": "t", "phase": "scheduled", "restart_at": now + 600, "waiting_jobs": 0,
                   "message": "m", "commit": "c", "updated_at": now, "expires_at": now + 3600,
                   "stops_running_jobs": False}
live = u.current_notice()
u._read = lambda: {"id": "t", "phase": "done", "expires_at": now - 1}
print("@@@" + json.dumps({"live": live, "expired": u.current_notice()}))
''')
    res = json.loads(out.splitlines()[-1][3:])
    check("a notice that has not expired comes back with every field the banner reads",
          res["live"] and set(res["live"]) >= {"id", "phase", "restart_at", "waiting_jobs", "message",
                                              "commit", "updated_at", "expires_at", "stops_running_jobs"},
          str(res["live"]))
    check("one past its expires_at comes back as no notice", res["expired"] is None, str(res["expired"]))

    print("\n== 3. the deploy request ==")
    admin = admin_client()
    for bad, why in [({"notice_minutes": 121}, "121 minutes"), ({"notice_minutes": -1}, "-1 minutes"),
                     ({"message": "x" * 501}, "a 501-character message")]:
        r = admin.post("/api/admin/deploy", json={"action": "report", **bad})
        check(f"{why} is refused with 400", r.status_code == 400, f"{r.status_code} {r.text[:120]}")
    r = admin.post("/api/admin/deploy", json={"action": "cancel"})
    check("cancel with no update announced is a 409", r.status_code == 409, f"{r.status_code} {r.text[:120]}")

    print("\n== 4. update.sh's own functions ==")
    harness = "\n".join([
        "set -euo pipefail",
        'warn(){ echo "WARN $*"; }; die(){ echo "DIE $*"; exit 1; }',
        "PGUSER_VAL=$(sed -n 's/^QC_AGENT_POSTGRES_USER=//p' .env); PGUSER_VAL=${PGUSER_VAL:-qc_agent}",
        "PGDB_VAL=$(sed -n 's/^QC_AGENT_POSTGRES_DB=//p' .env); PGDB_VAL=${PGDB_VAL:-qc_agent}",
        "COMPOSE=(docker compose -f docker-compose.yml)",
        "[ -f docker-compose.override.yml ] && COMPOSE+=(-f docker-compose.override.yml)",
        'psql_stack() { "${COMPOSE[@]}" exec -T postgres psql -At -U "$PGUSER_VAL" -d "$PGDB_VAL" "$@"; }',
        shell_function("post_notice"), shell_function("cancel_requested"),
        'NOTICE_ID=notice01-$$; RESTART_AT=$(( $(date +%s) + 600 )); FORCE=1; TARGET_SHA=0123456789abcdef',
        'NOTICE_MESSAGE="it\'s a \\"quoted\\" note; back\\\\slash"',
        'post_notice imminent $(( $(date +%s) - 5 )) 3',
        'echo "ROW=$(psql_stack -c "SELECT value FROM app_config WHERE key=\'update_notice\'")"',
        'cancel_requested && echo CANCEL1=yes || echo CANCEL1=no',
        'psql_stack -c "INSERT INTO app_config (key,value) VALUES (\'update_cancel\', jsonb_build_object(\'id\',\'someone-else\')) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value" >/dev/null',
        'cancel_requested && echo CANCEL2=yes || echo CANCEL2=no',
        'psql_stack -c "UPDATE app_config SET value=jsonb_build_object(\'id\',\'$NOTICE_ID\') WHERE key=\'update_cancel\'" >/dev/null',
        'cancel_requested && echo CANCEL3=yes || echo CANCEL3=no',
    ])
    try:
        proc = subprocess.run(["bash", "-c", harness], cwd=str(REPO), capture_output=True, text=True, timeout=120)
        out = proc.stdout
        row_line = next((ln for ln in out.splitlines() if ln.startswith("ROW=")), "ROW={}")
        row = json.loads(row_line[4:] or "{}")
        check("post_notice writes the phase, restart time and job count",
              row.get("phase") == "imminent" and row.get("restart_at") and row.get("waiting_jobs") == 3, str(row)[:200])
        check("and the stops-running-jobs flag from --force", row.get("stops_running_jobs") is True, str(row)[:200])
        check("and the message with quotes and a backslash intact",
              row.get("message") == 'it\'s a "quoted" note; back\\slash', repr(row.get("message")))
        time.sleep(2.5)  # past the notice route's 2 s cache
        served = new_client().get("/api/notice").json().get("notice")
        check("the api serves no notice for it, because it had expired", served is None, str(served))
        check("cancel_requested is no with no cancel row", "CANCEL1=no" in out, out[-200:])
        check("no for a cancel naming another update", "CANCEL2=no" in out, out[-200:])
        check("and yes for its own", "CANCEL3=yes" in out, out[-200:] + proc.stderr[-200:])
    finally:
        _psql("DELETE FROM app_config WHERE key IN ('update_notice','update_cancel')")
    summary()


if __name__ == "__main__":
    main()
