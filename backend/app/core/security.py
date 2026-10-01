"""Passwords and access tokens.

Two deliberately boring primitives, both from well-reviewed code rather than
anything clever:

**Password hashing: scrypt, from the standard library.** A password hash must
be slow on purpose, so that an attacker holding a stolen `users` table can only
try a few thousand guesses per second instead of billions. scrypt is also
memory-hard, which blunts GPU cracking. It ships with Python (`hashlib.scrypt`),
so there is no dependency to audit. Every hash carries its own parameters and
salt, so the cost can be raised later without invalidating existing hashes.

**Access tokens: HS256 JWTs via PyJWT.** The token says *who* you are and
nothing else. It carries a user id, never groups or roles. Groups are resolved
from the database on every request, which costs one indexed lookup and buys the
property this project is about: revoking someone's access takes effect on their
very next request, not when their token expires. A token that embedded groups
would keep granting HR access for up to an hour after someone left HR.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

import jwt

from app.core.config import Settings

#: Pinned, never read from the token header. Letting the token choose its own
#: algorithm is how "alg: none" and RS256/HS256 confusion attacks work.
JWT_ALGORITHM = "HS256"

# scrypt cost parameters: N=2^14, r=8, p=1 is the commonly recommended
# interactive-login setting (~16MB of memory, tens of milliseconds per hash).
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32


class TokenError(Exception):
    """The token is missing, malformed, expired, or not signed by us."""


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Return a self-describing hash: scrypt$N$r$p$salt$key (base64)."""
    salt = secrets.token_bytes(_SALT_BYTES)
    key = _scrypt(password, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return "$".join(
        ["scrypt", str(_SCRYPT_N), str(_SCRYPT_R), str(_SCRYPT_P), _b64(salt), _b64(key)]
    )


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time comparison against a stored hash.

    Returns False for a missing or malformed hash instead of raising, so a user
    with no password set simply cannot log in with one.
    """
    if not stored:
        return False
    try:
        scheme, n, r, p, salt_b64, key_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = _unb64(key_b64)
        actual = _scrypt(password, _unb64(salt_b64), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_KEY_BYTES, maxmem=64 * 1024**2
    )


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


#: Verified against when the email is unknown, so "no such user" and "wrong
#: password" take the same time and an attacker cannot use response latency
#: to discover which emails have accounts.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    expires_at: dt.datetime
    expires_in: int


def create_access_token(
    user_id: uuid.UUID, settings: Settings, *, now: dt.datetime | None = None
) -> IssuedToken:
    """Sign a short-lived token whose only claim about the user is their id."""
    secret = _secret(settings)
    issued_at = now or dt.datetime.now(dt.UTC)
    ttl = dt.timedelta(minutes=settings.access_token_ttl_minutes)
    expires_at = issued_at + ttl
    claims = {
        "sub": str(user_id),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": issued_at,
        "exp": expires_at,
        # Unique per token, so a specific token can be found in logs or added
        # to a denylist later without touching any other.
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)
    return IssuedToken(token=token, expires_at=expires_at, expires_in=int(ttl.total_seconds()))


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    """Verify signature, expiry, issuer and audience; return the user id."""
    try:
        claims = jwt.decode(
            token,
            _secret(settings),
            algorithms=[JWT_ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
        return uuid.UUID(claims["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token has expired") from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise TokenError("invalid token") from exc


def _secret(settings: Settings) -> str:
    if settings.jwt_secret is None:
        raise TokenError("JWT_SECRET is not configured")
    return settings.jwt_secret.get_secret_value()
