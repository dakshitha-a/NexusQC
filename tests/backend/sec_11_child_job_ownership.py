#!/usr/bin/env python3
"""A sub-job is as private as the master it belongs to.
Regression test for R-001, with R-090 alongside it.

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 PYTHONPATH=$PWD \
      python3 tests/backend/sec_11_child_job_ownership.py

R-001. A batch, scan, ensemble or geometry-set master is submitted with an
owner; its children were submitted with none, on the reasoning (recorded in
`_queue_owner`'s own docstring) that only a master is individually reachable
and therefore only a master needs an ownership row. `GET /api/jobs/{id}`
serves any job id, so the reasoning was wrong. Measured on the live
deployment during the review: a user who owned nothing asked for the master
`186fe458ec9e` and got 404, asked for its child `0d87ea39ec68` and got 200,
one request apart, with the 17 KB job record and a 16 KB artifact download
attached. `check_owner_or_admin` treats an absent owner as legacy-unowned and
lets it through, which is correct for a job created before auth existed and
wrong for a child created five seconds ago by an owned parent.

The scheduler already knew who the child belonged to: `JobManager.submit`
enqueues with `owner_user_id or _queue_owner(...)`, and `_queue_owner` walks
`parent_job_id` precisely so a child lands in its owner's fair queue. The
access check never asked the same question.

Two halves, and the script checks both.

**The resolution logic, in process, with no database.** `effective_owner`
walks the parent chain. Exercised here against a stub owner table and a
temporary job tree, so it runs anywhere, including against a working tree
whose code the deployment has not been rebuilt onto yet. Checks that a
child resolves to its master's owner, that an ownerless master still
resolves to None (the settled "unowned jobs are visible to everyone"
decision, which this must not break), that a cycle in `parent_job_id`
terminates instead of spinning a request thread, and that a non-job kind
never pays for the walk.

**The boundary, live, through nginx.** Two accounts. A owns a master with
children; B owns nothing. Every one of B's reads of A's master and of A's
children must be refused, and A's own reads of them must succeed. The
master/child pair comes from whatever the deployment already holds, so this
half is skipped with a printed reason if no owned master with children
exists rather than being reported as a pass.

R-090 rides along at the end: `GET /api/projects/{id}` used to render a row
per member job with no per-job check, while both of its siblings, the
add-jobs path and the zip download, check each job individually. Checked
here by reading the route's source, because reproducing it needs an
admin-assembled cross-user project that no ordinary flow creates.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import BASE_URL, admin_client, check, mint_invite, register, skip, summary  # noqa: E402

def _restore_label(job_id: str, previous: str | None) -> None:
    """Undo a successful write probe. `write_meta` only ever adds keys, so
    the original derived label comes back by removing the override rather
    than by writing the old string back over it."""
    meta = REPO / "data" / "jobs" / job_id / "meta.json"
    if not meta.exists():
        return
    d = json.loads(meta.read_text())
    if d.pop("label", None) is not None:
        meta.write_text(json.dumps(d))
        print(f"        (restored {job_id}'s label to {previous!r})")


print("R-001: a sub-job is as private as its master\n")

# --- half one: the resolution logic, in process -----------------------------
print("1. effective_owner walks the parent chain (in process, stubbed table)")

from app.auth import models as auth_models, ownership  # noqa: E402
from app.chemistry.jobs import base as jobs_base  # noqa: E402

_TABLE = {("job", "master"): "alice", ("job", "grandmaster"): "alice"}
_real_get_owner = auth_models.get_owner
_real_jobs_dir = jobs_base.JOBS_DIR

tmp = Path(tempfile.mkdtemp(prefix="r001-"))
for jid, parent in (("master", None), ("child", "master"), ("orphanmaster", None),
                    ("orphanchild", "orphanmaster"), ("loopa", "loopb"), ("loopb", "loopa")):
    (tmp / jid).mkdir()
    (tmp / jid / "spec.json").write_text(json.dumps({"job_id": jid, "parent_job_id": parent}))

auth_models.get_owner = lambda kind, rid: _TABLE.get((kind, rid))
ownership.models.get_owner = auth_models.get_owner
jobs_base.JOBS_DIR = tmp
try:
    check("a master resolves to its own owner",
          ownership.effective_owner("job", "master") == "alice",
          f"got {ownership.effective_owner('job', 'master')!r}")
    check("a child with no row of its own resolves to its master's owner",
          ownership.effective_owner("job", "child") == "alice",
          f"got {ownership.effective_owner('job', 'child')!r}")
    check("a child of an unowned master stays unowned (the settled visible-to-all case)",
          ownership.effective_owner("job", "orphanchild") is None,
          f"got {ownership.effective_owner('job', 'orphanchild')!r}")
    check("a parent_job_id cycle terminates instead of spinning",
          ownership.effective_owner("job", "loopa") is None,
          f"got {ownership.effective_owner('job', 'loopa')!r}")
    check("a non-job kind never walks (a thread has no parent_job_id)",
          ownership.effective_owner("thread", "child") is None,
          f"got {ownership.effective_owner('thread', 'child')!r}")
finally:
    auth_models.get_owner = _real_get_owner
    ownership.models.get_owner = _real_get_owner
    jobs_base.JOBS_DIR = _real_jobs_dir

# --- half two: the boundary, live -------------------------------------------
print("\n2. the boundary itself, through nginx, with two accounts")

admin = admin_client()

# An OWNED master with children. Ownership is the part that makes the probe
# mean anything: an unowned master is readable by everyone by design, so its
# children being readable proves nothing, and picking the first master with
# children found one of those the moment another test run left a job behind.
# The owner list is read once, in bulk, the way the job list route does it.
# Whether the master is owned is settled below, by asking as a stranger,
# rather than read from an admin route: that is the same question the finding
# is about and the answer that matters.
target = None
for row in admin.get("/api/jobs").json():
    jid = row["job_id"]
    kids = admin.get(f"/api/jobs/{jid}/children")
    if kids.status_code != 200:
        continue
    items = kids.json().get("items") or []
    if not items:
        continue
    target = (jid, [k["job_id"] for k in items])
    break

if not target:
    print("  [SKIP] this deployment holds no master with children, so there is nothing")
    print("         to prove the boundary against. Seed a batch job and re-run.")
else:
    master_id, child_ids = target
    print(f"  master {master_id} with {len(child_ids)} child(ren)")
    tok = mint_invite(admin)
    b_client, b_user = register(tok, password="R001-probe-passphrase-long-enough!")

    r = b_client.get(f"/api/jobs/{master_id}")
    master_denied = r.status_code == 404
    if not master_denied:
        # Not a failure: an unowned master is visible to everyone by a settled
        # decision, so its children being visible proves nothing either way.
        # Reported as a skip so it cannot pass quietly.
        skip("the cross-user probe",
             f"master {master_id} is readable by any user, so it is unowned "
             f"(the settled visible-to-all case) and its children prove nothing")
    else:
        check("a user who owns nothing is refused the master", True, "HTTP 404")

    if master_denied:
        for cid in child_ids:
            r = b_client.get(f"/api/jobs/{cid}")
            check(f"and refused its child {cid}", r.status_code == 404,
                  f"HTTP {r.status_code}",
                  f"HTTP {r.status_code}: the child of a private master was served")
            r = b_client.get(f"/api/jobs/{cid}/download")
            check(f"and refused that child's artifact download", r.status_code == 404,
                  f"HTTP {r.status_code}",
                  f"HTTP {r.status_code}, {len(r.content)} bytes handed over")
            # Write access is in scope, so it is probed -- and undone
            # immediately if the probe succeeds, because these are the
            # deployment's own jobs and a failing security test must not
            # leave its evidence written into someone's job list. The
            # rename route stores an override in meta.json; clearing the
            # key restores the label the app derives from the spec.
            before = admin.get(f"/api/jobs/{cid}").json().get("label")
            r = b_client.patch(f"/api/jobs/{cid}", json={"label": "R-001 write probe"})
            check("and cannot rename it", r.status_code == 404, f"HTTP {r.status_code}")
            if r.status_code == 200:
                _restore_label(cid, before)

    # the admin, who is not the owner either, must still see everything
    r = admin.get(f"/api/jobs/{child_ids[0]}")
    check("an admin still reads the child (admins are trusted operators)",
          r.status_code == 200, f"HTTP {r.status_code}")

    # The probe account owns nothing by design, so deleting it removes
    # exactly itself. Tests clean up what they create.
    b_client.post("/api/auth/logout")
    admin.delete(f"/api/admin/users/{b_user['id']}")

# --- R-090 -------------------------------------------------------------------
print("\n3. R-090: the project detail route checks each member job")
import inspect  # noqa: E402
from server.routes import projects as projects_route  # noqa: E402

src = inspect.getsource(projects_route.get_project)
check("get_project calls check_owner_or_admin per member job",
      "check_owner_or_admin" in src, "",
      "it still renders every member row unconditionally, unlike _check_jobs "
      "and the zip download beside it")

print("\n4. the quota sweep treats master and children as one unit")
# Children gained ownership rows in this change, so a per-user eviction
# sweep can now see them. Deleting one on its own would leave a scan with
# a hole nothing reports, and delete_job_dir already removes a master's
# children with it, so the eviction unit has to be the master.
from app.auth import storage_quota  # noqa: E402

qsrc = inspect.getsource(storage_quota._job_candidates)
check("_job_candidates skips sub-jobs",
      'if spec.get("parent_job_id"):' in qsrc and "continue" in qsrc, "",
      "a sub-job is still an eviction candidate in its own right")
check("and folds their bytes into the master's size",
      "child_bytes" in qsrc, "",
      "a sweep would under-count what deleting a master reclaims")

dsrc = inspect.getsource(jobs_base.delete_job_dir)
check("delete_job_dir clears the ownership row it is deleting",
      "forget_ownership" in dsrc, "",
      "the eviction sweep and the admin purge leave rows behind for jobs "
      "that no longer exist")

summary()
