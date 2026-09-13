#!/usr/bin/env python3
"""The knowledge base establishes identity before it fetches, refuses what it
cannot keep, cleans up after a failed ingest, and lets an admin read.
Regression test for R-006, R-047, R-048 and R-049.

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 PYTHONPATH=$PWD \
      python3 tests/backend/kb_01_quota_and_scope.py

R-006. `POST /api/kb/sources/url` made two outbound requests --
`robots_disallows` then `fetch_page` -- before it resolved who was calling,
with no host restriction and redirects followed. That reaches a cloud
metadata endpoint or anything else on this host's network, for whoever asked.
The middleware's Origin check is not authentication: it rejects a request
with no Origin header and passes one that claims the deployment's own.

R-047. The write came first and `enforce_quota()` second, and eviction is
oldest-first with the just-written item last in that order. So a source
larger than the caller's whole allowance was accepted with a 201, everything
older was deleted to make room for it, and then it was deleted too -- leaving
an id that 404s on the next request and a shorter history than before.

R-048. A failed ingestion left the bytes on disk, and both accounting paths
enumerate from Chroma, so a file with no chunks was counted by no quota,
listed by no route and reclaimed by no eviction.

R-049. `_content_search_dirs(None)` -- the admin branch -- searched
UPLOADS_DIR itself and the shared corpus, while an owned upload lives one
level deeper, and `_find_source_file` requires the resolved parent to BE the
directory it searched. So an admin could list every user's sources and
preview none of them, which is the opposite of what that function's own
docstring says.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import admin_client, check, mint_invite, register, summary  # noqa: E402

print("R-006: identity before the fetch\n")
from server.routes import kb as kb_route  # noqa: E402

# Code lines only. The comments in this function name both fetch calls
# while explaining why the order matters, so a plain index() finds the prose
# rather than the call.
src = inspect.getsource(kb_route.add_url_source)
code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
owner_at = code.index("owner = _owner_key(request)")
robots_at = code.index("robots_disallows(body.url)")
fetch_at = code.index("fetch_page(body.url)")
check("the caller is resolved before robots.txt is fetched", owner_at < robots_at,
      f"owner at {owner_at}, robots at {robots_at}",
      "the app fetches a URL of the caller's choosing before it knows who they are")
check("and before the page itself is fetched", owner_at < fetch_at,
      f"owner at {owner_at}, fetch at {fetch_at}")
check("current_user_or_none is called, so an unauthenticated caller 401s first",
      "current_user_or_none(request)" in code[:owner_at + 200], "")

print("\nR-047: a source that cannot be kept is refused, not accepted and deleted")
from app.auth import storage_quota  # noqa: E402

check("there is an up-front single-item check",
      hasattr(storage_quota, "single_item_can_ever_fit"), "")
for fn in ("add_source", "add_text_source", "add_url_source"):
    fsrc = inspect.getsource(getattr(kb_route, fn))
    check(f"{fn} refuses an oversized source before writing it",
          "_refuse_if_oversized" in fsrc, "")
    check(f"{fn} reports a source the quota pass then removed",
          "_refuse_if_evicted" in fsrc, "",
          "a 201 naming an id that 404s on the next request is the worst of "
          "the three outcomes")
from server.routes import uploads as uploads_route  # noqa: E402

usrc = inspect.getsource(uploads_route.upload_file)
check("and POST /api/uploads does both too",
      "single_item_can_ever_fit" in usrc and "get_upload(owner, record" in usrc, "")

print("\nR-048: a failed ingest leaves nothing on disk")
for fn in ("add_source", "add_text_source", "add_url_source"):
    fsrc = inspect.getsource(getattr(kb_route, fn))
    check(f"{fn} unlinks the file when ingestion raises",
          "dest.unlink(missing_ok=True)" in fsrc, "",
          "the bytes stay on disk, counted by no quota, listed by no route, "
          "reclaimed by no eviction")

print("\nR-049: an admin can preview a per-user file")
dsrc = inspect.getsource(kb_route._content_search_dirs)
check("the admin branch searches each per-user directory",
      "UPLOADS_DIR.iterdir()" in dsrc, "",
      "it searches UPLOADS_DIR itself, and an owned upload is one level deeper")

# Live: user B uploads a text source, admin previews it.
admin = admin_client()
tok = mint_invite(admin)
user, pub = register(tok, password="kb-probe-passphrase-long-enough!")
name = "kb01-admin-preview-probe.txt"
r = user.post("/api/kb/sources/text",
              json={"filename": name, "doc_type": "paper", "text": "KB01 marker text."})
check("a user can add a text source", r.status_code == 201, f"HTTP {r.status_code}")
if r.status_code == 201:
    source = (r.json() or {}).get("source") or name
    got = admin.get(f"/api/kb/sources/{source}/content")
    check("and an admin can read it back", got.status_code == 200,
          f"HTTP {got.status_code}",
          f"HTTP {got.status_code}: the admin lists every user's sources and "
          f"can preview none of them")
    if got.status_code == 200:
        check("with the content the user wrote", "KB01 marker" in got.text, got.text[:80])
    user.delete(f"/api/kb/sources/{source}")
user.post("/api/auth/logout")
admin.delete(f"/api/admin/users/{pub['id']}")

summary()
