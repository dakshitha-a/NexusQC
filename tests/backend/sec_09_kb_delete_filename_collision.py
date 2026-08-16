"""SEC-09: app/rag/store.py's delete_source(source, owner_filter=None) --
the path an admin's DELETE /api/kb/sources/{source} takes -- matches
Chroma chunks by `{"source": source}` with NO owner constraint at all
(server/routes/kb.py's remove_source docstring already documents this as a
known, accepted gap). Two different users uploading identically-named
files are disjoint documents under the hood, but an admin deleting by
filename removes BOTH users' chunks in one call, not just the one the
admin meant to remove.

Proof: users A and B each upload a file with the SAME filename (different
content), admin deletes it, then confirm from EACH user's own
GET /api/kb/sources that both users' sources are gone -- not just the one
an admin presumably intended to purge.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

SHARED_FILENAME = "qatest_collision_doc.txt"


def _upload(client, content: str) -> None:
    files = {"file": (SHARED_FILENAME, content.encode(), "text/plain")}
    r = client.post("/api/kb/sources", files=files, data={"doc_type": "manual"})
    return r


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

    r_del = admin.delete(f"/api/kb/sources/{SHARED_FILENAME}")
    check("admin delete-by-filename succeeds", r_del.status_code == 200, f"{r_del.status_code} {r_del.text[:200]}")
    print(f"admin delete response: {r_del.json()}")

    a_gone = not _has_source(client_a)
    b_gone = not _has_source(client_b)
    check("user A's source was removed (expected -- admin meant to delete something)", a_gone)
    check(
        "user B's UNRELATED, identically-named source survived the admin's delete",
        not b_gone,
        "user B's source was ALSO deleted -- confirms the filename-only collision: an admin deleting "
        "one user's KB source silently deletes every other user's identically-named source too",
    )

    cleanup_user(admin, user_a["id"])
    cleanup_user(admin, user_b["id"])
    summary(exit_on_failure=False)


if __name__ == "__main__":
    main()
