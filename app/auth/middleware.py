"""Two request-level protections, both deliberately lightweight rather than
per-route dependencies, since they apply uniformly to (almost) every route:

1. CSRF: SameSite=Lax cookies already block the common cross-site attachment
   cases, but a same-site form/link with a matching cookie can still slip
   through on some browsers/configurations -- an Origin-header allowlist
   check on every state-changing request closes the practical remaining
   surface with zero frontend plumbing. Not a double-submit token: every
   mutating route in this app is already POST/PATCH/DELETE (no state-
   changing GETs), and frontend/src/lib/api.ts's downloadPlotPng already
   bypasses the shared request() wrapper with its own raw fetch() -- a
   double-submit header would need separate wiring there too, for no real
   security gain over an Origin check given this deployment is always
   same-origin-behind-nginx.

2. (removed 2026-08-25) A public-access soft toggle used to live here,
   keyed on an X-Access-Channel header nginx set on its public listener.
   Both are gone; this deployment is intranet and tailnet only.
   per listener (see nginx/nginx.conf), overwriting any client-supplied
   value -- this middleware trusts that header completely and must never be
   reachable from anywhere that doesn't sit behind nginx's overwrite. For
   the "public" channel only, it additionally checks the admin-settable
   app_config flag and returns a clean 503 instead of proxying through to a
   route handler. The intranet channel is never gated by this flag, by
   design -- the two are independent controls per the deployment's
   requirements.
"""
from __future__ import annotations

import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.auth import models

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Everything an admin needs to log in, watch an update and be told when it is
# over, plus the two unauthenticated probes the updater and the browser poll.
_MAINTENANCE_EXEMPT = (
    "/api/health",
    "/api/version",
    "/api/auth/",
    "/api/admin/",
)

# Read through a short TTL rather than per request. This runs on EVERY request
# on a sync path, and a Postgres round trip per request to answer a question
# whose answer changes twice per update would be a real cost for no accuracy
# anyone can perceive -- two seconds of lag on entering maintenance is
# invisible next to the ninety seconds the api takes to come back.
_MAINT_TTL_SECONDS = 2.0
_maint_cache: dict[str, float | bool] = {"value": False, "checked_at": 0.0}


def _maintenance_mode() -> bool:
    now = time.monotonic()
    if now - float(_maint_cache["checked_at"]) < _MAINT_TTL_SECONDS:
        return bool(_maint_cache["value"])
    try:
        value = bool(models.get_app_config("maintenance_mode", False))
    except Exception:
        # A deployment mid-restart may briefly have no database to ask. Failing
        # open is right here: the alternative is locking every user out of a
        # healthy deployment because one query timed out.
        value = False
    _maint_cache["value"] = value
    _maint_cache["checked_at"] = now
    return value


class AccessControlMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: list[str]):
        super().__init__(app)
        # Static list covers local dev (the Vite dev server's own origin,
        # e.g. http://localhost:5173 -- see SERVER_CORS_ORIGINS). The
        # deployed case is handled dynamically below instead of via a
        # static config entry, since nginx's two listeners (intranet/
        # public, nginx/nginx.conf) have different hostnames and this
        # should work behind either without a separate env var per
        # listener to keep in sync.
        self._allowed_origins = set(allowed_origins)

    async def dispatch(self, request: Request, call_next):
        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin")
            # A real browser always sends Origin on a state-changing
            # fetch()/XHR, same-origin or not -- that's what this whole
            # check leans on. Treating a MISSING Origin as automatically
            # allowed (the previous `if origin is not None and ...`) skips
            # the check entirely for exactly the requests it exists to
            # police, since nothing stops a non-browser or crafted request
            # from simply omitting the header. Confirmed empirically (not
            # just reasoned through) while building the auth/admin test
            # suite: a POST with no Origin header reached the route handler
            # every time, admin and non-admin routes alike.
            if origin is None:
                return JSONResponse({"detail": "origin not allowed"}, status_code=403)
            if origin not in self._allowed_origins:
                # Reconstruct this deployment's own origin from what nginx
                # forwarded (proxy_common.conf sets Host and
                # X-Forwarded-Proto) -- a same-origin request behind either
                # nginx listener is allowed without needing that listener's
                # hostname hardcoded into a config list anywhere.
                forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
                host = request.headers.get("host", "")
                deployed_origin = f"{forwarded_proto}://{host}"
                if origin != deployed_origin:
                    return JSONResponse({"detail": "origin not allowed"}, status_code=403)

        # There used to be a public-channel check here, keyed on the
        # X-Access-Channel header nginx set. It went with the public
        # listener on 2026-08-25: with no public listener, no request can
        # carry that channel, and a branch that can never be taken is worse
        # than no branch -- it reads as a control that is protecting
        # something. The Origin check above is unrelated and stays.
        #
        # What follows is the same SHAPE as that removed branch, and the note
        # above is the reason it is worth saying plainly why this one can
        # actually be taken: scripts/update.sh --maintenance sets
        # app_config.maintenance_mode immediately before it recreates the
        # stack, and clears it again from its EXIT trap, so this is reachable
        # on any deployment during any in-app update.
        if _maintenance_mode():
            path = request.url.path
            # Exempt by path, not by role: this middleware runs before any
            # dependency has resolved a user, so there is nothing here that
            # knows who is calling. /api/auth/* stays open so an admin can
            # still log in to watch, /api/admin/* so they can still drive the
            # panel, and health/version because the updater itself polls them
            # and a browser needs to know when to reload. A non-admin who
            # reaches /api/admin/* gets the usual 403 from require_admin,
            # which is the real boundary and is unaffected by any of this.
            if not any(path.startswith(p) for p in _MAINTENANCE_EXEMPT):
                return JSONResponse(
                    {
                        "detail": "maintenance",
                        "message": "NexusQC is being updated and will be back shortly.",
                    },
                    status_code=503,
                    headers={"Retry-After": "30"},
                )

        return await call_next(request)
