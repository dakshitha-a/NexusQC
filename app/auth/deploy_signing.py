"""One canonical form for a deployment request, and one HMAC over it.

Shared, in spirit, between two languages: this module signs, and
`scripts/deploy_runner.sh` on the host verifies with the same recipe in
`python3 -c`. Keeping the recipe in one place and describing it exactly is
the only thing that stops the two drifting apart, since nothing can import
across that boundary.

Why it exists. The api cannot update its own deployment and is deliberately
not given the means to (no checkout, no docker socket, no npm). So the admin
panel's Apply button writes a request into `data/deploy/request.json`, and a
host-side runner picks it up and runs `scripts/update.sh`. `data/` is
bind-mounted into the container, the name is fixed, and the runner never read
`requested_by`. That made the existence of the file the entire authority for
a host deployment action, and R-002 showed an ordinary user could create a
file at an arbitrary path through a knowledge-base upload. Two independent
fixes were available and both were taken: the upload path is sanitised, and
the runner now verifies who asked.

The canonical form is the request's own fields, minus the signature, as
JSON with sorted keys, no spaces after separators, and UTF-8 encoding. Any
field the runner reads must be inside it or the signature protects nothing:
`action`, `ref`, `drain` and `force` all are, and so are `id` and
`requested_at`, which is what lets the runner reject a replayed request.
"""
from __future__ import annotations

import hashlib
import hmac
import json


def canonical_bytes(payload: dict) -> bytes:
    """The exact bytes both sides sign. `signature` is excluded, obviously,
    and booleans are left as JSON booleans rather than stringified so the
    shell side can reproduce this with json.dumps and nothing else."""
    body = {k: v for k, v in payload.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_deploy_request(payload: dict) -> str:
    """Hex HMAC-SHA256, or "" when no secret is configured.

    An empty signature is not an error here. A deployment that predates this
    variable must keep starting and must keep serving its admin panel; it is
    the runner that refuses to act on an unsigned update or rollback, and it
    says why, which puts the message where the operator can act on it.
    """
    from app.config import DEPLOY_SECRET
    if not DEPLOY_SECRET:
        return ""
    return hmac.new(DEPLOY_SECRET.encode("utf-8"), canonical_bytes(payload), hashlib.sha256).hexdigest()


def verify_deploy_request(payload: dict) -> bool:
    """Constant-time check. Used by tests; the host runner has its own copy
    of the recipe because it cannot import this."""
    from app.config import DEPLOY_SECRET
    if not DEPLOY_SECRET:
        return False
    got = str(payload.get("signature") or "")
    want = sign_deploy_request(payload)
    return bool(want) and hmac.compare_digest(got, want)
