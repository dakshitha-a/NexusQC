#!/usr/bin/env python3
"""P5.2: the account, quota and admin findings from the 2026-09 review.

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 \\
      PYTHONPATH=$PWD python3 tests/backend/sec_16_account_hardening.py

Nine findings, none of them a hole an outsider could walk through, all of
them a promise the app was making and not keeping. They are together because
they are one cluster of the same kind: the account's own data and the numbers
the app quotes about it.

R-044, the per-user quota pass measured only EVICTABLE bytes. Candidates
exclude everything that must not be evicted (a running job, a pinned thread,
a scan child), so a user whose usage was mostly non-evictable measured under
their cap while genuinely over it, and the pass took nothing away at all. The
console showed one number and the enforcement acted on another, both called
"jobs and chat".

R-045, accepting two shares at once. The quota check and the copy are a
check-then-act with no lock, and share acceptance is the one quota path that
never evicts, so an overage created that way is permanent.

R-046, "download all my data" left out conversations, plots, projects and
scan frames. The same account's quota bills it for chat history, and the
account-deletion path deletes conversations, so of the three descriptions of
what an account holds, this one was the odd one out.

R-052, bug-report attachments. Three 5MB screenshots per report was the only
bound; nothing capped how many reports one account could file, and
attachments deliberately do not count against storage quota, so this was an
unmetered write channel.

R-082, PATCH on an unknown bug report answered 200 and wrote an audit row
saying a report had been changed. A malformed id answered 500, which tells a
prober their input got further than a well-formed miss would. The audit log
is documented as append-only and therefore has to be true.

R-083, two orbital-render error paths returned a 500 carrying orca_plot's own
stderr, which names engine binaries and host paths.

R-087, "delete all my data" left the caller's plots and project archives
behind and reported counts that did not mention either.

R-088, `revoke_session` had no callers and `expires_at` was never acted on,
so the sessions table only ever grew and said every session ever opened was
still open.

R-089, an admin invite accepted any `ttl_hours`, unlike the password-reset
route beside it, so an invite that can mint another admin could sit
redeemable for years.

The route checks below need the running stack. The rest is in-process.
"""
from __future__ import annotations

import inspect
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402


def section(title: str):
    """Run one section, reporting anything missing as a FAIL rather than a
    traceback, so the pre-fix run of this file reports every check instead of
    stopping at the first name the old code does not have."""
    def wrap(fn):
        def run(*args):
            print(f"\n== {title} ==")
            try:
                fn(*args)
            except Exception as exc:  # noqa: BLE001
                check(title, False, f"{type(exc).__name__}: {exc}")
        run.__name__ = fn.__name__
        return run
    return wrap


@section("R-089: an invite's lifetime is bounded like a password reset's")
def _invite_ttl(admin) -> None:
    r = admin.post("/api/admin/invites", json={"role": "admin", "ttl_hours": 24 * 365 * 5})
    check("a five-year invite is refused", r.status_code == 400, f"HTTP {r.status_code}")
    r = admin.post("/api/admin/invites", json={"role": "user", "ttl_hours": 0})
    check("a zero-hour invite is refused", r.status_code == 400, f"HTTP {r.status_code}")
    r = admin.post("/api/admin/invites", json={"role": "user", "ttl_hours": 72})
    check("the documented maximum is still accepted", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code == 200:
        admin.post(f"/api/admin/invites/{r.json()['token']}/revoke")


@section("R-082: a bug report that does not exist is a 404, not a 200")
def _bug_report_patch(admin) -> None:
    missing = str(uuid.uuid4())
    r = admin.patch(f"/api/admin/bug-reports/{missing}", json={"status": "closed"})
    check("a well-formed id for no report answers 404",
          r.status_code == 404, f"HTTP {r.status_code}: {r.text[:120]}")
    r = admin.patch("/api/admin/bug-reports/not-a-uuid", json={"status": "closed"})
    check("a malformed id answers 404 too, not a 500 that says it got further",
          r.status_code == 404, f"HTTP {r.status_code}: {r.text[:120]}")
    audit = admin.get("/api/admin/audit-log")
    if audit.status_code == 200:
        rows = audit.json()
        touched = [a for a in rows if a.get("target") in (missing, "not-a-uuid")]
        check("and no audit row claims either report was changed",
              not touched, f"{len(touched)} row(s) written for a report that does not exist")


@section("R-083: a failed orbital render does not hand back engine paths")
def _orbital_error() -> None:
    from server.routes import jobs as jobs_routes
    src = inspect.getsource(jobs_routes.get_orbital_cube)
    check("the ORCA branch logs the exception instead of returning it",
          "logger.exception(" in src, "")
    check("and the detail it returns carries no exception text",
          "detail=f\"orca_plot failed: {exc}\"" not in src, "")
    check("a non-positive orbital index is refused at the route as a 400",
          "Orbital index must be 1 or greater" in src, "")


@section("R-088: a session is recorded as ended when it ends")
def _sessions() -> None:
    from app.auth import models
    from server.routes import auth as auth_routes
    check("revoke_session has a caller now",
          "models.revoke_session(" in inspect.getsource(auth_routes.logout), "")
    check("deactivating an account revokes its rows too",
          hasattr(models, "revoke_sessions_for_user"), "")
    check("expired rows are removed rather than kept for ever",
          hasattr(models, "delete_expired_sessions"), "")
    from app.agent.job_watcher import JobWatcher
    check("and something actually runs that sweep",
          "delete_expired_sessions()" in inspect.getsource(JobWatcher._start_quota_pass), "")


@section("R-044: the quota pass measures what the user actually holds")
def _quota_measure() -> None:
    from app.auth import storage_quota
    src = inspect.getsource(storage_quota.enforce_all_quotas)
    check("each pass starts from the usage report, not from its own candidates",
          "usage_report()[\"per_user\"]" in src or 'usage_report()["per_user"]' in src, "")
    for field in ("kb_bytes", "upload_bytes", "jobs_and_chat_bytes"):
        check(f"the {field} pass enforces against {field}", f'"{field}"' in src, "")


@section("R-045: two shares accepted at once cannot both slip past the cap")
def _share_lock() -> None:
    from server.routes import shares
    src = inspect.getsource(shares.accept_share)
    check("the check and the copy are held under a per-recipient lock",
          "_accept_lock_for(" in src, "")
    check("the lock is keyed on the recipient, not taken globally",
          "def _accept_lock_for(user_id" in inspect.getsource(shares), "")


@section("R-046 and R-087: what the archive holds and what the purge deletes")
def _own_data() -> None:
    from app.auth import storage_quota
    from server.routes import auth as auth_routes
    dl = inspect.getsource(auth_routes.download_my_data)
    for what, needle in (("conversations", 'f"conversations/'),
                         ("plots", 'f"{stem}/record.json"'),
                         ("project archives", 'f"projects/')):
        check(f"the archive includes {what}", needle in dl, "")
    check("scan and ensemble frames arrive as owned sub-jobs, and that is said so",
          "R-001" in dl, "")

    purge = inspect.getsource(storage_quota.purge_own_data)
    check("the self-purge deletes the caller's plots", "delete_plot(" in purge, "")
    check("the self-purge deletes the caller's project archives",
          "delete_projects(" in purge, "")
    check("and it still leaves conversations alone, which is the point of it",
          "_thread_candidates(" not in purge, "")
    check("the counts it returns name plots and projects",
          '"plot_ids"' in purge and '"project_ids"' in purge, "")


@section("R-052: bug-report attachments have a ceiling and a rate")
def _bug_limits(user_client) -> None:
    from server.routes import bugs
    check("reports are rate-limited per account, not per address",
          "enforce_for_key(" in inspect.getsource(bugs.submit_bug_report), "")
    check("and there is a total-bytes ceiling per account",
          hasattr(bugs, "MAX_ATTACHMENT_BYTES_PER_USER"), "")

    # The rate limit itself, driven for real: file more reports than the
    # window allows and require the surplus to be refused. Bodies are tiny and
    # carry no attachments, so this costs nothing but rows.
    limit = getattr(bugs, "BUG_REPORT_RATE_LIMIT_MAX", 12)
    codes = []
    for i in range(limit + 3):
        r = user_client.post(
            "/api/bug-reports",
            data={"body": f"sec_16 rate-limit probe {i}"},
            files=[],
        )
        codes.append(r.status_code)
    accepted = sum(1 for c in codes if c == 200)
    refused = sum(1 for c in codes if c == 429)
    print(f"  filed {len(codes)} reports: {accepted} accepted, {refused} refused with 429")
    check(f"the account's {limit}-per-hour budget is enforced",
          refused >= 1 and accepted <= limit,
          f"accepted={accepted} refused={refused} codes={codes}")


def main() -> None:
    admin = admin_client()
    tok = mint_invite(admin, "user")
    client, info = register(tok)
    uid = (info.get("user") or info).get("id")
    try:
        _invite_ttl(admin)
        _bug_report_patch(admin)
        _orbital_error()
        _sessions()
        _quota_measure()
        _share_lock()
        _own_data()
        _bug_limits(client)
    finally:
        # The probe's own reports go with the account: bug_reports.user_id is
        # ON DELETE SET NULL, so deleting the user would otherwise leave them
        # in the admin inbox with no reporter. Deleted by id first.
        try:
            for row in admin.get("/api/admin/bug-reports").json():
                if str(row.get("body", "")).startswith("sec_16 rate-limit probe"):
                    admin.delete(f"/api/admin/bug-reports/{row['id']}")
        except Exception as exc:  # noqa: BLE001
            print(f"  could not clean up the probe's bug reports: {exc}")
        cleanup_user(admin, uid)
    summary()


if __name__ == "__main__":
    main()
