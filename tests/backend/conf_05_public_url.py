"""The deployment's public address: the base of every invite and reset link.

Links used to be built from the admin's own browser origin. On a Tailscale
node shared with each user rather than joined to one tailnet, every recipient
reaches the host at a different address, so a link carrying the admin's was
dead for all of them. The address now has three sources, most specific
first: the admin-console override (`public_url` in app_config), the
QC_AGENT_PUBLIC_URL the operator set in .env, and nothing (the frontend then
uses the browser's origin, as before).

What this covers: the field is admin-only; a valid origin is stored and
reported back with source "setting"; anything that is not an origin (a path,
a query, a wrong scheme, a bad port, a non-string) is refused with a 422
naming the rule and leaves the stored value alone; blank clears the override
and the source falls back; the change is audited. The previous value is
restored at the end, whatever happened, so the deployment's own setting
survives the test.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fixtures import admin_client, check, cleanup_user, mint_invite, register, summary  # noqa: E402

ORIGIN = "https://example-host.test:8444"


def main() -> None:
    admin = admin_client()
    before = admin.get("/api/admin/config").json()
    check("GET /api/admin/config reports public_url and its source",
          "public_url" in before and before.get("public_url_source") in ("setting", "env", "browser"),
          f"{before.get('public_url')!r} from {before.get('public_url_source')!r}")
    prior_override = before["public_url"] if before["public_url_source"] == "setting" else ""

    token = mint_invite(admin)
    user, user_pub = register(token)
    try:
        r = user.patch("/api/admin/config", json={"key": "public_url", "value": ORIGIN})
        check("a non-admin cannot set it", r.status_code == 403, str(r.status_code))

        r = admin.patch("/api/admin/config", json={"key": "public_url", "value": ORIGIN + "/"})
        check("an admin sets an origin (a trailing slash is dropped)", r.status_code == 200 and r.json()["value"] == ORIGIN, r.text[:200])
        cfg = admin.get("/api/admin/config").json()
        check("GET reflects it with source 'setting'",
              cfg["public_url"] == ORIGIN and cfg["public_url_source"] == "setting", f"{cfg['public_url']} {cfg['public_url_source']}")

        for bad in ["https://x/path", "https://x?y=1", "https://x/#frag", "ftp://x", "not a url",
                    "https://x:99999", "https://user:pw@x", 5, True]:
            r = admin.patch("/api/admin/config", json={"key": "public_url", "value": bad})
            check(f"{bad!r} is refused with a 422 naming the rule",
                  r.status_code == 422 and "origin" in r.text, f"{r.status_code} {r.text[:120]}")
        cfg = admin.get("/api/admin/config").json()
        check("a refused value leaves the stored one alone", cfg["public_url"] == ORIGIN, cfg["public_url"])

        r = admin.patch("/api/admin/config", json={"key": "public_url", "value": "   "})
        cfg = admin.get("/api/admin/config").json()
        check("blank clears the override and the source falls back to env or browser",
              r.status_code == 200 and cfg["public_url_source"] in ("env", "browser"),
              f"{cfg['public_url']!r} from {cfg['public_url_source']}")
        if cfg["public_url_source"] == "browser":
            check("with nothing configured the value is empty, never a guess", cfg["public_url"] == "")

        entries = admin.get("/api/admin/audit-log").json()
        mine = [e for e in entries if e.get("action") == "config_update" and e.get("target") == "public_url"]
        check("each change is audited as config_update on public_url", len(mine) >= 2, f"{len(mine)} entries")
    finally:
        admin.patch("/api/admin/config", json={"key": "public_url", "value": prior_override})
        cleanup_user(admin, user_pub["id"])
    after = admin.get("/api/admin/config").json()
    check("the deployment's own setting is back where it was", after["public_url"] == before["public_url"], after["public_url"])

    summary()


if __name__ == "__main__":
    main()
