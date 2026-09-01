"""P1.2: GET /api/users/search, the share picker's lookup.

This route is a new privacy surface. Before it existed, no ordinary user
could learn that any other account was there at all: ownership was purely a
filter, and every list route stripped other people's rows before they
reached the client. Sharing needs a picker, and the user chose prefix search
across all active users, so what matters is that the route gives up exactly
what a picker needs and nothing more.

The projection is the point of most of these checks. models.get_user_by_id
and get_user_by_login both SELECT password_hash, and server/routes/auth.py's
_user_public still carries email and role, so the obvious three ways to
build this route would each have published something. The assertions below
are written against the response keys directly rather than against a
"contains no secrets" heuristic, so a later widening of the projection
fails here rather than shipping.

Creates two qatest_ users and deletes both at the end.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import (  # noqa: E402
    admin_client, check, cleanup_user, mint_invite, qatest_username, register, summary,
)

ALLOWED_KEYS = {"id", "username", "first_name", "last_name"}


def main() -> None:
    admin = admin_client()
    alice_name = qatest_username()
    bob_name = qatest_username()

    alice_c, alice = register(mint_invite(admin), username=alice_name,
                              first_name="Ada", last_name="Lovelace")
    bob_c, bob = register(mint_invite(admin), username=bob_name,
                          first_name="Grace", last_name="Hopper")

    try:
        # --- The projection ------------------------------------------------
        r = alice_c.get("/api/users/search", params={"q": bob_name[:6]})
        check("search returns 200", r.status_code == 200, f"status={r.status_code}")
        rows = r.json() if r.status_code == 200 else []
        hit = next((x for x in rows if x["username"] == bob_name), None)
        check("search finds another user by username prefix", hit is not None,
              f"{len(rows)} row(s) returned")

        if hit is not None:
            extra = set(hit) - ALLOWED_KEYS
            check("projection is exactly id/username/first_name/last_name",
                  not extra, f"keys={sorted(hit)}",
                  fail_detail=f"unexpected key(s) exposed: {sorted(extra)}")
            check("email is not exposed", "email" not in hit)
            check("role is not exposed", "role" not in hit)
            check("password_hash is not exposed", "password_hash" not in hit)
            check("first/last name are returned for display",
                  hit.get("first_name") == "Grace" and hit.get("last_name") == "Hopper",
                  f"{hit.get('first_name')} {hit.get('last_name')}")

        # --- Searching by real name, not just handle -----------------------
        r = alice_c.get("/api/users/search", params={"q": "Hopp"})
        found = any(x["username"] == bob_name for x in r.json())
        check("search matches on last name", found,
              "a user is findable by the name a colleague would actually type")

        r = alice_c.get("/api/users/search", params={"q": "Grac"})
        check("search matches on first name",
              any(x["username"] == bob_name for x in r.json()))

        # --- The caller is not their own share target ----------------------
        r = alice_c.get("/api/users/search", params={"q": alice_name[:6]})
        check("caller is excluded from their own results",
              not any(x["username"] == alice_name for x in r.json()),
              "you cannot share with yourself")

        # --- Enumeration bounds --------------------------------------------
        for short in ("", "a"):
            r = alice_c.get("/api/users/search", params={"q": short})
            ok = r.status_code == 200 and r.json() == []
            check(f"a {len(short)}-character query returns [] rather than the roster",
                  ok, f"status={r.status_code}, rows={len(r.json()) if r.status_code == 200 else 'n/a'}")

        # A bare wildcard must be a literal, not a match-everything.
        r = alice_c.get("/api/users/search", params={"q": "%%"})
        check("LIKE wildcards are escaped, not honoured",
              r.status_code == 200 and r.json() == [],
              fail_detail=f"'%%' returned {len(r.json()) if r.status_code == 200 else '?'} row(s)")

        # --- Suspended accounts are not offerable --------------------------
        admin.patch(f"/api/admin/users/{bob['id']}", json={"is_active": False})
        r = alice_c.get("/api/users/search", params={"q": bob_name[:6]})
        check("a suspended account is not a share target",
              not any(x["username"] == bob_name for x in r.json()),
              "an offer to a suspended user could never be accepted")
        admin.patch(f"/api/admin/users/{bob['id']}", json={"is_active": True})

        # --- Authentication ------------------------------------------------
        from fixtures import new_client
        anon = new_client()
        r = anon.get("/api/users/search", params={"q": bob_name[:6]})
        check("an unauthenticated caller cannot search users",
              r.status_code in (401, 404), f"status={r.status_code}")

    finally:
        alice_c.close()
        bob_c.close()
        cleanup_user(admin, alice["id"])
        cleanup_user(admin, bob["id"])
        admin.close()

    summary()


if __name__ == "__main__":
    main()
