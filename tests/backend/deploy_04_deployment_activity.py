"""The two read-only deployment routes the admin panel's Deployment section
is built on: GET /api/admin/deployment and GET /api/admin/activity, plus the
unauthenticated GET /api/version they are compared against.

What each check is actually asserting, since a bare pass count says nothing:

  * /api/version answers without a session at all. It has to, because the
    browser reads it while the deployment is mid-restart or has no auth layer
    mounted, and because a tab that has just been logged out still needs to
    know whether to reload.
  * The commit it reports and the one /api/admin/deployment reports are the
    same string. They come from the same environment variable, and the whole
    point of baking it in rather than reading the OCI label is that the
    process can answer for itself -- so a disagreement means one of them is
    reading something else.
  * /api/admin/activity's per-user numbers add up to its own totals. The
    totals are what the confirm dialog will show and the rows are what
    justifies it, so they cannot be computed independently and drift.
  * A job this script submits itself appears against the account that
    submitted it. This is the only check that proves the ownership join is
    real rather than an empty dict that happens to sum to zero.

Every job and conversation this script creates is deleted before it exits.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client, check, new_client, summary,
)

SHA_LEN = 40
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
        cwd=str(COMPOSE_DIR), capture_output=True, text=True, timeout=120,
    )
    return proc.returncode, proc.stdout, proc.stderr


def main() -> None:
    admin = admin_client()

    # --- /api/version, unauthenticated -------------------------------------
    anon = new_client()
    r_ver = anon.get("/api/version")
    check("GET /api/version answers without a session", r_ver.status_code == 200,
          f"{r_ver.status_code} {r_ver.text[:120]}")
    version_commit = r_ver.json().get("commit", "")
    check("/api/version reports a commit field", bool(version_commit), repr(version_commit))

    # --- /api/admin/deployment ---------------------------------------------
    r_dep = admin.get("/api/admin/deployment")
    check("GET /api/admin/deployment answers for an admin", r_dep.status_code == 200,
          f"{r_dep.status_code} {r_dep.text[:150]}")
    dep = r_dep.json()

    check(
        "the deployment route and /api/version report the same commit",
        dep.get("api_commit") == version_commit,
        f"deployment={dep.get('api_commit')!r} version={version_commit!r}",
    )
    check(
        "api_commit_known agrees with whether the commit is a real sha",
        dep.get("api_commit_known") == (dep.get("api_commit") != "unknown"),
        f"known={dep.get('api_commit_known')} commit={dep.get('api_commit')!r}",
    )
    if dep.get("api_commit_known"):
        check(
            "a known commit is a full 40-character sha, not a truncated one",
            len(dep["api_commit"]) == SHA_LEN and all(c in "0123456789abcdef" for c in dep["api_commit"]),
            dep["api_commit"],
        )

    # --- /api/admin/activity, shape and internal consistency ---------------
    r_act = admin.get("/api/admin/activity")
    check("GET /api/admin/activity answers for an admin", r_act.status_code == 200,
          f"{r_act.status_code} {r_act.text[:150]}")
    act = r_act.json()

    for key in ("users", "unowned", "totals"):
        check(f"activity carries a {key!r} block", key in act, sorted(act))

    users, totals, unowned = act["users"], act["totals"], act["unowned"]
    for field in ("running_jobs", "pending_jobs", "open_streams"):
        per_user = sum(u[field] for u in users)
        check(
            f"totals[{field!r}] equals the sum of the rows plus the unowned count",
            totals[field] == per_user + unowned[field],
            f"total={totals[field]} rows={per_user} unowned={unowned[field]}",
        )

    check(
        "users_interrupted counts exactly the rows flagged would_be_interrupted",
        totals["users_interrupted"] == sum(1 for u in users if u["would_be_interrupted"]),
        f"total={totals['users_interrupted']}",
    )
    check(
        "would_be_interrupted is true for a row if and only if it has a running job or an open stream",
        all(u["would_be_interrupted"] == bool(u["running_jobs"] or u["open_streams"]) for u in users),
        "one or more rows disagree with their own counts",
    )
    check(
        "the admin running this script appears in the user list",
        any(u["role"] == "admin" for u in users),
        f"{len(users)} rows, roles={sorted({u['role'] for u in users})}",
    )

    # --- the ownership join is real ----------------------------------------
    #
    # This asserts that a non-terminal job with a recorded owner is counted
    # against that owner's row rather than falling into the unowned bucket.
    # Every other check above would pass just as happily against an
    # implementation that returned an empty dict, because this deployment
    # normally has nothing running.
    #
    # The job state is written directly rather than by running a calculation,
    # and that is deliberate. Two earlier versions of this check submitted a
    # real job and polled for it: water/STO-3G finished in under a second, and
    # so did benzene/cc-pVTZ (this host has 255 cores), so the poll only ever
    # saw a terminal job and the check failed against working code. Making the
    # calculation big enough to reliably outlive the poll would put a
    # multi-minute wait in a suite in exchange for testing PySCF, which is not
    # what this file is for. What is under test is the join --
    # _iter_job_ids_on_disk + read_status + all_owners + the grouping -- and
    # that reads the same files whether a real worker wrote them or this test
    # did.
    admin_id = next((u["id"] for u in users if u["role"] == "admin"), None)
    check("an admin user id was found to attribute a job to", bool(admin_id), str(admin_id))

    probe_id = ""
    if admin_id:
        code = (
            "import json, uuid, time\n"
            "from pathlib import Path\n"
            "from app.config import JOBS_DIR\n"
            "from app.auth.models import record_ownership\n"
            "jid = 'qatest' + uuid.uuid4().hex[:6]\n"
            "d = Path(JOBS_DIR) / jid; d.mkdir(parents=True)\n"
            "(d / 'spec.json').write_text(json.dumps({'job_id': jid, 'task': 'single_point',\n"
            "    'subtype': 'gs', 'method': 'hf', 'engine': 'pyscf', 'molecule': {}, 'params': {}}))\n"
            "(d / 'status.json').write_text(json.dumps({'status': 'running',\n"
            "    'message': 'qatest probe', 'updated_at': time.time()}))\n"
            f"record_ownership('job', jid, '{admin_id}')\n"
            "print(jid)\n"
        )
        rc, out, err = _exec_api(code)
        probe_id = out.strip().splitlines()[-1].strip() if out.strip() else ""
        check("a running job owned by the admin was staged", rc == 0 and probe_id.startswith("qatest"),
              f"rc={rc} id={probe_id!r} {err[-160:]}")

    if probe_id:
        # Poll rather than read once. The route answers from the shared job
        # index in app/chemistry/jobs/base.py, which is rebuilt at most once a
        # second (R-051, so an open admin console does not walk the job
        # directory on every poll). This probe writes its job from a separate
        # `docker compose exec` process, so the api's own index does not learn
        # about it through write_status and only picks it up when its second is
        # up. Reading immediately therefore tests the cache's age rather than
        # the join this check is about. Three seconds is three times the TTL.
        deadline = time.time() + 3.0
        snap = admin.get("/api/admin/activity").json()
        row = next((u for u in snap["users"] if u["id"] == admin_id), None)
        while time.time() < deadline and not (row and row["running_jobs"] >= 1):
            time.sleep(0.25)
            snap = admin.get("/api/admin/activity").json()
            row = next((u for u in snap["users"] if u["id"] == admin_id), None)
        check(
            "the staged job is counted against its owner's row",
            bool(row) and row["running_jobs"] >= 1,
            f"row running_jobs={row['running_jobs'] if row else 'no row'}",
        )
        check(
            "and it is not double-counted into the unowned bucket",
            snap["unowned"]["running_jobs"] == 0,
            f"unowned running={snap['unowned']['running_jobs']}",
        )
        check(
            "its owner is therefore flagged as one an update would interrupt",
            bool(row) and row["would_be_interrupted"],
            f"would_be_interrupted={row['would_be_interrupted'] if row else 'no row'}",
        )
        check(
            "and the totals moved with it",
            snap["totals"]["running_jobs"] >= 1 and snap["totals"]["users_interrupted"] >= 1,
            f"totals={snap['totals']}",
        )

        rc, _, err = _exec_api(
            "import shutil\n"
            "from pathlib import Path\n"
            "from app.config import JOBS_DIR\n"
            f"shutil.rmtree(Path(JOBS_DIR) / '{probe_id}', ignore_errors=True)\n"
            "print('removed')\n"
        )
        check("the staged job was removed again", rc == 0, err[-160:])

        after = admin.get("/api/admin/activity").json()
        check(
            "and the deployment reads as idle again once it is gone",
            after["totals"]["running_jobs"] == 0,
            f"totals={after['totals']}",
        )

    summary()


if __name__ == "__main__":
    main()
