"""SEC-09 (fix regression test): app/rag/store.py's delete_source(source,
owner_filter=None) -- the path an admin's DELETE /api/kb/sources/{source}
used to always take -- matched Chroma chunks by `{"source": source}` with
NO owner constraint at all. Two different users uploading identically-
named files are disjoint documents under the hood, but an admin deleting
by filename removed BOTH users' chunks in one call, not just the one the
admin meant to remove.

The fix (server/routes/kb.py's remove_source): an unscoped delete
(no ?owner= query param) now refuses with a 409 and lists the colliding
owners when more than one exists for that filename, instead of silently
deleting all of them; passing ?owner=<id> deletes exactly that owner's
copy. The single-owner case (the common one, and the only one possible on
a no-auth deployment) is unaffected.

Proof, since 2026-09-24 when admins stopped reaching other users' content:
users A and B each upload a file with the SAME filename (different content).
An admin's delete by that name, with or without ?owner=, touches neither
copy. A's own delete removes only A's copy, leaving B's untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

SHARED_FILENAME = "qatest_collision_doc.txt"


def _upload(client, content: str):
    files = {"file": (SHARED_FILENAME, content.encode(), "text/plain")}
    return client.post("/api/kb/sources", files=files, data={"doc_type": "manual"})


def _has_source(client) -> bool:
    r = client.get("/api/kb/sources")
    r.raise_for_status()
    return any(s["source"] == SHARED_FILENAME for s in r.json())


def main() -> None:
    admin = admin_client()
    token_a = mint_invite(admin)
    token_b = mint_invite(admin)
    client_a, user_a = register(token_a)
    client_b, user_b = register(token_b)

    r_a = _upload(client_a, "This is user A's document content, upload one.")
    r_b = _upload(client_b, "This is user B's UNRELATED document content, upload two.")
    check("user A's upload succeeded", r_a.status_code == 201, f"{r_a.status_code} {r_a.text[:200]}")
    check("user B's upload succeeded", r_b.status_code == 201, f"{r_b.status_code} {r_b.text[:200]}")

    check("user A sees their own uploaded source", _has_source(client_a))
    check("user B sees their own uploaded source", _has_source(client_b))

    # An admin's delete by that name. It used to reach every user's copy,
    # which is the bug this script was written for. Since 2026-09-24 an
    # admin is scoped to their own sources like anyone else, and this admin
    # has none by this name, so nothing is touched at all.
    r_admin = admin.delete(f"/api/kb/sources/{SHARED_FILENAME}")
    check("an admin's delete by that name touches no user's copy (404)",
          r_admin.status_code == 404, f"status={r_admin.status_code} body={r_admin.text[:200]}")
    r_admin = admin.delete(f"/api/kb/sources/{SHARED_FILENAME}", params={"owner": user_a["id"]})
    check("and ?owner= cannot point an admin at someone else's copy (404)",
          r_admin.status_code == 404, f"status={r_admin.status_code} body={r_admin.text[:200]}")
    check("user A's source still exists", _has_source(client_a))
    check("user B's source still exists", _has_source(client_b))

    # Each owner's own delete removes only their own copy.
    r_a_del = client_a.delete(f"/api/kb/sources/{SHARED_FILENAME}")
    check("user A deletes their own copy", r_a_del.status_code == 200,
          f"{r_a_del.status_code} {r_a_del.text[:200]}")
    check("user A's source is gone", not _has_source(client_a))
    check("user B's identically named source survived", _has_source(client_b),
          fail_detail="user B's source was also deleted -- identically named sources are not isolated")
    r_b_del = client_b.delete(f"/api/kb/sources/{SHARED_FILENAME}")
    check("user B deletes their own copy", r_b_del.status_code == 200,
          f"{r_b_del.status_code} {r_b_del.text[:200]}")

    cleanup_user(admin, user_a["id"])
    cleanup_user(admin, user_b["id"])
    summary()


if __name__ == "__main__":
    main()
