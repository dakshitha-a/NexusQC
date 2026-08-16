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

2. Public-access soft toggle: nginx sets X-Access-Channel: intranet|public
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

# In-process cache for the public-access flag -- avoids a Postgres round
# trip on every single public-channel request. A few seconds of staleness
# after an admin flips the toggle is an accepted tradeoff (the host-level
# firewall kill switch, scripts/toggle_public_access.sh, is the mechanism
# for anything that needs to be instant/unconditional -- see that script
# and CLAUDE.md's deployment notes for why the two are deliberately
# separate layers).
_PUBLIC_ACCESS_CACHE_TTL = 5.0
_cache: dict = {"value": True, "checked_at": 0.0}


def _public_access_enabled() -> bool:
    now = time.monotonic()
    if now - _cache["checked_at"] > _PUBLIC_ACCESS_CACHE_TTL:
        _cache["value"] = bool(models.get_app_config("public_access_enabled", default=True))
        _cache["checked_at"] = now
    return _cache["value"]


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

        channel = request.headers.get("x-access-channel", "intranet")
        if channel == "public" and not _public_access_enabled():
            return JSONResponse(
                {"detail": "Public access is currently disabled by an administrator. Please use the campus intranet, or try again later."},
                status_code=503,
            )

        return await call_next(request)
