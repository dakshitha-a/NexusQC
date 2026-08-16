"""Password hashing and JWT encode/decode. argon2id (via argon2-cffi) over
passlib[bcrypt] -- argon2id is the current OWASP-recommended KDF, and
avoids bcrypt's silent truncation of any password input past 72 bytes
(a real footgun: two different passwords sharing the same first 72 bytes
would hash identically under bcrypt without either party noticing).
pyjwt over python-jose for the JWT itself -- simpler, sufficient for HS256,
no need for python-jose's broader (and heavier) JOSE feature surface here.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import JWT_ALGORITHM, JWT_SECRET, SESSION_TTL_SECONDS

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _require_secret() -> str:
    if not JWT_SECRET:
        # Fail loud, not with a forged-token vulnerability: an empty/missing
        # secret would make every token verify against a shared "" key,
        # which is not a secret at all. This should only ever be reachable
        # in the containerized deployment (DATABASE_URL set, auth routes
        # wired in) -- local dev without QC_AGENT_JWT_SECRET never calls
        # into this module at all.
        raise RuntimeError("QC_AGENT_JWT_SECRET is not set -- refusing to sign or verify a session token")
    return JWT_SECRET


def issue_token(user_id: str, session_id: str, role: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "sid": session_id,
        "role": role,
        "iat": now,
        "exp": now + SESSION_TTL_SECONDS,
    }
    return jwt.encode(payload, _require_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """Returns the decoded payload, or None on any invalid/expired/
    malformed token -- callers treat None uniformly as "not authenticated"
    rather than distinguishing failure reasons, since none of those
    distinctions change what the caller does (redirect to login either
    way)."""
    try:
        return jwt.decode(token, _require_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


def new_session_id() -> str:
    return str(uuid.uuid4())
