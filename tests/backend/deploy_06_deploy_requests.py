"""The request channel between the admin panel and the host-side runner.

The api cannot update its own deployment and is deliberately not given the
means to -- no docker socket, no checkout. It writes a request into data/deploy
and scripts/deploy_runner.sh, running on the host as the operator, answers it.
These checks cover the api's half of that contract, which is the half a
malformed or hostile request would reach first.

What each check is for:

  * An action outside the fixed set is refused with a 400 here rather than
    written out and quietly ignored by the runner. The caller finds out.
  * With no runner alive, anything that would need one is refused with a 503
    naming the host command, instead of queueing a request nothing will ever
    claim. An Apply button that silently does nothing is worse than no button,
    and this is the check that keeps that promise honest.
  * A ping is allowed through even with no runner alive, because a ping is
    precisely how the panel finds out that the runner is dead.
  * Two requests cannot be queued at once. The runner claims a request by
    moving the file, so a second one written before the first is claimed would
    overwrite it and be silently lost.
  * The status route validates its id before touching the filesystem, since
    that id becomes a path segment.
  * Every deploy action is written to the audit log, because "who restarted
    the deployment" is exactly the question asked afterwards.

Nothing here starts a real update; that is exercised end to end against a
disposable second deployment rather than against whatever stack the suite is
pointed at.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, summary  # noqa: E402

# QC_AGENT_COMPOSE_DIR overrides where the compose files are looked for, the
# same way tests/frontend/*.spec.mjs does. Without it these `docker compose
# exec` calls always talk to the checkout this file lives in, even when
# QC_AGENT_TEST_BASE_URL points the HTTP half at a different deployment -- so
# the script would set up state on one stack and assert against another, and
# every check that depended on the setup would fail for a reason that has
# nothing to do with the code under test.
COMPOSE_DIR = Path(os.environ.get("QC_AGENT_COMPOSE_DIR")
                   or Path(__file__).resolve().parent.parent.parent)


def _exec_api(code: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-c", code],
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _set_runner_heartbeat(age_seconds: float | None) -> None:
    """Make the runner look alive, stale, or absent.

    Written from inside the container so it lands with the container's own
    uid, which is what the api would see in reality.
    """
    if age_seconds is None:
        code = (
            "from app.config import DEPLOY_DIR\n"
            "p = DEPLOY_DIR / 'runner.json'\n"
            "p.unlink(missing_ok=True)\n"
            "print('removed')\n"
        )
    else:
        code = (
            "import json, time\n"
            "from app.config import DEPLOY_DIR\n"
            "DEPLOY_DIR.mkdir(parents=True, exist_ok=True)\n"
            f"(DEPLOY_DIR / 'runner.json').write_text(json.dumps({{'alive_at': time.time() - {age_seconds}}}))\n"
            "print('written')\n"
        )
    _exec_api(code)


def _clear_pending() -> None:
    _exec_api(
        "from app.config import DEPLOY_DIR\n"
        "(DEPLOY_DIR / 'request.json').unlink(missing_ok=True)\n"
        "print('cleared')\n"
    )


def main() -> None:
    admin = admin_client()

    # Snapshot so this script restores whatever the deployment had, rather
    # than leaving a fabricated heartbeat behind that would make a real panel
    # offer an Apply button for a runner that is not there.
    rc, out, _ = _exec_api(
        "from app.config import DEPLOY_DIR\n"
        "p = DEPLOY_DIR / 'runner.json'\n"
        "print(p.read_text() if p.exists() else '')\n"
    )
    original_heartbeat = out.strip()

    try:
        _clear_pending()

        # --- an unknown action never reaches the runner --------------------
        r = admin.post("/api/admin/deploy", json={"action": "rm -rf /"})
        check("an action outside the fixed set is refused with 400",
              r.status_code == 400, f"{r.status_code} {r.text[:120]}")

        # --- no runner: refuse, and say what to do instead -----------------
        _set_runner_heartbeat(None)
        r = admin.get("/api/admin/deployment")
        runner = r.json().get("runner", {})
        check("with no heartbeat the deployment reports no runner installed",
              runner.get("installed") is False and runner.get("alive") is False, str(runner))

        r = admin.post("/api/admin/deploy", json={"action": "update"})
        check("an update is refused with 503 when nothing would claim it",
              r.status_code == 503, f"{r.status_code} {r.text[:160]}")
        check("and the refusal names the host command instead of failing blankly",
              "update.sh" in r.text, r.text[:200])

        # --- a stale heartbeat is not a live runner ------------------------
        _set_runner_heartbeat(600)
        r = admin.get("/api/admin/deployment")
        runner = r.json().get("runner", {})
        check("a heartbeat 10 minutes old reads as installed but not alive",
              runner.get("installed") is True and runner.get("alive") is False, str(runner))

        # --- a ping is allowed through precisely to discover that ----------
        r = admin.post("/api/admin/deploy", json={"action": "ping"})
        check("a ping is accepted even with no live runner, since that is how you find out",
              r.status_code == 200, f"{r.status_code} {r.text[:160]}")
        ping_id = r.json().get("id", "") if r.status_code == 200 else ""

        # --- one queued request at a time ----------------------------------
        r2 = admin.post("/api/admin/deploy", json={"action": "ping"})
        check("a second request is refused with 409 while one is still queued",
              r2.status_code == 409, f"{r2.status_code} {r2.text[:160]}")
        _clear_pending()

        # --- the status route validates its id -----------------------------
        # A single path segment that reaches the route and fails ITS check,
        # rather than one the router rejects before the handler runs -- the
        # earlier version used ..%2f..%2f and passed on a router 404, which
        # would have kept passing with the validation deleted.
        r = admin.get("/api/admin/deploy/bad.id.with.dots")
        check("an id that reaches the route but is not alphanumeric is refused with 400",
              r.status_code == 400, f"{r.status_code} {r.text[:120]}")

        r = admin.get("/api/admin/deploy/doesnotexist99")
        check("an unknown but well-formed id is a 404, not a 500",
              r.status_code == 404, f"{r.status_code} {r.text[:120]}")

        # --- the audit log records who asked -------------------------------
        if ping_id:
            log = admin.get("/api/admin/audit-log").json()
            entries = [e for e in log if str(e.get("action", "")).startswith("deploy_")]
            check("the deploy request was written to the audit log",
                  any(e.get("target") == ping_id for e in entries),
                  f"{len(entries)} deploy_* entries; looking for target={ping_id}")

    finally:
        _clear_pending()
        if original_heartbeat:
            _exec_api(
                "from app.config import DEPLOY_DIR\n"
                "DEPLOY_DIR.mkdir(parents=True, exist_ok=True)\n"
                f"(DEPLOY_DIR / 'runner.json').write_text({original_heartbeat!r})\n"
                "print('restored')\n"
            )
        else:
            _set_runner_heartbeat(None)
        # The ping run's own directory, if one was created.
        _exec_api(
            "import shutil\n"
            "from app.config import DEPLOY_DIR\n"
            "for d in DEPLOY_DIR.iterdir():\n"
            "    if d.is_dir():\n"
            "        shutil.rmtree(d, ignore_errors=True)\n"
            "print('cleaned')\n"
        )

    summary()


if __name__ == "__main__":
    main()
