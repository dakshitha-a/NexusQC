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

Proof: users A and B each upload a file with the SAME filename (different
content) -- an unscoped admin delete must now be REFUSED (409) with both
sources still present afterward, and a delete scoped to A's own id via
?owner= must remove only A's copy, leaving B's untouched.
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

    # An UNSCOPED admin delete against a colliding filename must now be
    # refused, not silently touch both users' data.
    r_unscoped = admin.delete(f"/api/kb/sources/{SHARED_FILENAME}")
    check(
        "FIX VERIFIED: an unscoped delete against a colliding filename is refused (409), not applied",
        r_unscoped.status_code == 409,
        f"status={r_unscoped.status_code} body={r_unscoped.text[:200]}",
    )
    print(f"unscoped delete response: {r_unscoped.status_code} {r_unscoped.text[:200]}")
    check(
        "FIX VERIFIED: user A's source still exists after the refused unscoped delete",
        _has_source(client_a),
    )
    check(
        "FIX VERIFIED: user B's source still exists after the refused unscoped delete",
        _has_source(client_b),
    )

    # A delete scoped to A's own id via ?owner= must remove ONLY A's copy.
    r_scoped = admin.delete(f"/api/kb/sources/{SHARED_FILENAME}", params={"owner": user_a["id"]})
    check(
        "FIX VERIFIED: an admin delete scoped to a specific owner via ?owner= succeeds",
        r_scoped.status_code == 200,
        f"{r_scoped.status_code} {r_scoped.text[:200]}",
    )
    print(f"owner-scoped delete response: {r_scoped.json() if r_scoped.status_code == 200 else r_scoped.text}")

    a_gone = not _has_source(client_a)
    b_still_here = _has_source(client_b)
    check("FIX VERIFIED: user A's source was removed by the owner-scoped delete", a_gone)
    check(
        "FIX VERIFIED: user B's UNRELATED, identically-named source survived the owner-scoped delete",
        b_still_here,
        fail_detail="user B's source was also deleted -- the owner scoping isn't actually isolating the two",
    )

    # Cleanup: only B's copy remains now, so an unscoped delete is
    # unambiguous again (single owner) and should succeed normally.
    r_cleanup = admin.delete(f"/api/kb/sources/{SHARED_FILENAME}")
    check(
        "an unscoped delete succeeds again once only one owner remains (no longer ambiguous)",
        r_cleanup.status_code == 200,
        f"{r_cleanup.status_code} {r_cleanup.text[:200]}",
    )

    cleanup_user(admin, user_a["id"])
    cleanup_user(admin, user_b["id"])
    summary()


if __name__ == "__main__":
    main()
