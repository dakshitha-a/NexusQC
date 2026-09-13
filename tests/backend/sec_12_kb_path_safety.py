#!/usr/bin/env python3
"""A client-supplied name never decides where a file is written.
Regression test for R-002, with R-005's other instances and R-008.

    QC_AGENT_TEST_BASE_URL=https://127.0.0.1:8444 PYTHONPATH=$PWD \
      python3 tests/backend/sec_12_kb_path_safety.py

R-002. Both knowledge-base write routes joined a caller-supplied filename
straight onto the upload directory. `add_text_source` took it from a Pydantic
`str | None` with no validator at all; `add_source` checked the extension and
nothing else. A `pathlib` join with an absolute string discards the left
operand, so no `../` was even needed:

    Path("/app/data/kb/uploads/user-123") / "/app/data/deploy/request.json"
    -> PosixPath("/app/data/deploy/request.json")

and `data/` is bind-mounted into the api container while
`scripts/deploy_runner.sh` polls `data/deploy/request.json` at that fixed
name and runs `scripts/update.sh` or `--rollback` on the host from what it
finds. So an ordinary user's knowledge-base upload could reach a host
deployment action. Two independent fixes each break that chain, and both are
taken here: the name is sanitised, and the runner verifies who asked.

R-005 is the habit the same file demonstrates: the READ path twenty lines
above already took `Path(source).name` and re-checked containment, with a
comment explaining exactly this hazard. It was applied in one direction. Two
more instances of the same habit live in the orbital cube route, where `gbw`
is allowlist-validated and the `spin` beside it in the same cache key is not,
and where the download NAME built from that key was slugified while the real
path built from it was not.

R-008: nginx served the whole of `data/deploy` unauthenticated, including
`runner.json`, which carried the host repo path and therefore the operator's
username.

The probes here write to harmless targets. They must not aim at
`data/deploy/request.json`, because on unfixed code they would succeed.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures import admin_client, check, mint_invite, register, skip, summary  # noqa: E402

MARKER = "r002-probe-marker.txt"
ESCAPES = [
    f"../{MARKER}",
    f"../../{MARKER}",
    f"/tmp/{MARKER}",
    f"subdir/{MARKER}",
    "",
    "..",
]

print("R-002: a knowledge-base upload cannot choose where it lands\n")

print("1. _safe_dest, in process")
from fastapi import HTTPException  # noqa: E402
from server.routes import kb as kb_route  # noqa: E402

for name in ESCAPES:
    try:
        dest = kb_route._safe_dest(None, name)
        inside = dest.resolve().parent == kb_route._upload_dir(None).resolve()
        check(f"_safe_dest({name!r}) stays inside the upload directory", inside,
              f"-> {dest}", f"-> {dest}, which is outside")
    except HTTPException as exc:
        check(f"_safe_dest({name!r}) is refused outright", True, f"HTTP {exc.status_code}")

ordinary = kb_route._safe_dest(None, "a-real-paper.pdf")
check("an ordinary name still works",
      ordinary.name == "a-real-paper.pdf"
      and ordinary.parent.resolve() == kb_route._upload_dir(None).resolve(),
      f"-> {ordinary}")

print("\n   and all three write paths go through it")
for fn in ("add_source", "add_text_source", "add_url_source"):
    src = inspect.getsource(getattr(kb_route, fn))
    check(f"{fn} uses _safe_dest", "_safe_dest" in src, "",
          "it still joins a name onto the upload directory directly")

print("\n2. the routes themselves, live")
admin = admin_client()
tok = mint_invite(admin)
user, _pub = register(tok, password="R002-probe-passphrase-long-enough!")

for name in ESCAPES[:3]:
    r = user.post("/api/kb/sources/text",
                  json={"filename": name, "doc_type": "paper", "text": "R-002 probe"})
    check(f"POST /api/kb/sources/text with filename={name!r} is refused",
          r.status_code == 400, f"HTTP {r.status_code}",
          f"HTTP {r.status_code}: the write was accepted")

leaked = sorted(p for p in (REPO / "data").rglob(MARKER))
leaked += sorted(Path("/tmp").glob(MARKER))
check("no probe file was written anywhere under data/ or /tmp",
      not leaked, f"{len(leaked)} found",
      f"written to: {', '.join(str(p) for p in leaked)}")
for p in leaked:
    p.unlink()
    print(f"        (removed the leaked probe file {p})")

print("\n3. R-005's other two instances: the orbital cube route")
from server.routes import jobs as jobs_route  # noqa: E402

src = inspect.getsource(jobs_route.get_orbital_cube)
check("spin is allowlisted, like gbw beside it in the same key",
      "_SPIN_VALUES" in src, "", "spin still reaches cube_key unvalidated")
check("a negative orbital index is refused",
      "index < 1" in src, "", "index still reaches ORCA's plotting as index - 1")
check("the cube path itself is contained, whatever cube_key turned out to be",
      "cube_path.resolve().parent" in src, "",
      "only the cosmetic download name is defended")

print("\n4. R-002's other half: the runner verifies who asked")
from app.auth.deploy_signing import canonical_bytes, sign_deploy_request  # noqa: E402
import app.config as cfg  # noqa: E402

payload = {"id": "abc123", "action": "update", "ref": "", "drain": False,
           "force": False, "requested_by": "u1", "requested_at": 1.0}
check("the signed body excludes the signature itself",
      b"signature" not in canonical_bytes(dict(payload, signature="x")),
      canonical_bytes(payload).decode()[:60])
_real = cfg.DEPLOY_SECRET
cfg.DEPLOY_SECRET = "test-secret"
try:
    sig = sign_deploy_request(payload)
    check("signing produces a hex digest", len(sig) == 64, f"{sig[:16]}...")
    check("changing the action changes the signature",
          sign_deploy_request(dict(payload, action="rollback")) != sig)
finally:
    cfg.DEPLOY_SECRET = _real

runner = (REPO / "scripts" / "deploy_runner.sh").read_text()
check("deploy_runner.sh verifies the signature before update/rollback/report",
      "request_signature_state" in runner, "",
      "the file is still the only authority")
check("and refuses when no secret is configured rather than proceeding",
      "nosecret" in runner and "refusing" in runner, "")
check("R-008: runner.json no longer carries the host repo path",
      '"repo"' not in runner and "$REPO_ROOT\\\"}" not in runner, "",
      "an unauthenticated GET still hands out the operator's username")

nginx_conf = (REPO / "nginx" / "nginx.conf").read_text()
check("R-008: nginx serves only per-run subdirectories under /deploy-status/",
      "location ~ ^/deploy-status/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+)$" in nginx_conf, "",
      "the whole of data/deploy is still aliased in")

print("\n5. and the fixed-name files are not served, live")
# Only meaningful when the file is actually on disk. A 404 for a file that
# does not exist proves nothing about the location block, and reporting it as
# a pass would be exactly the kind of check that looks green and tests
# nothing. This deployment has never run the host-side updater, so the files
# are usually absent and this half usually skips; the source check in
# section 4 is what covers the config in that case.
import httpx  # noqa: E402

deploy_dir = REPO / "data" / "deploy"
with httpx.Client(base_url=str(admin.base_url), verify=False, timeout=10) as anon:
    for name in ("runner.json", "request.json"):
        if not (deploy_dir / name).exists():
            skip(f"GET /deploy-status/{name} unauthenticated",
                 f"data/deploy/{name} does not exist on this deployment, so a 404 "
                 f"would not distinguish the nginx rule from the missing file")
            continue
        r = anon.get(f"/deploy-status/{name}")
        check(f"GET /deploy-status/{name} unauthenticated does not serve the file",
              r.status_code == 404, f"HTTP {r.status_code}",
              f"HTTP {r.status_code}: {r.text[:120]}")

admin.delete(f"/api/admin/users/{_pub['id']}")
summary()
