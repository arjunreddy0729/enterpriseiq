"""Password authentication.

Lives here rather than in the route module for the same reason retrieval does:
the route's job is to validate input, call one thing, and shape a response.
This is the one piece of logic in the API layer with real security properties,
which makes it the last place that should be reachable only through FastAPI.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    TokenError,
    create_access_token,
    verify_password,
)
from app.db.models import User

logger = get_logger(__name__)


class AuthError(Exception):
    """Credentials were rejected. Deliberately carries no detail about why."""


class AuthConfigurationError(Exception):
    """The server cannot issue tokens at all - an operator problem, not a
    caller problem, and reported as 503 rather than 401."""


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    expires_in: int
    expires_at: object


def authenticate(session: Session, settings: Settings, email: str, password: str) -> IssuedToken:
    """Verify a password and issue an access token.

    Raises AuthError for any credential failure, with no indication of which
    part failed.
    """
    if settings.jwt_secret is None:
        raise AuthConfigurationError("JWT_SECRET is not configured, so tokens cannot be issued.")

    email = email.strip().lower()
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()

    # Verify against a dummy hash for unknown emails so both failures take the
    # same time, and raise the same error for both, so neither the response
    # body nor the latency reveals which emails have accounts.
    stored = user.password_hash if user is not None else None
    valid = verify_password(password, stored or DUMMY_PASSWORD_HASH)
    if user is None or stored is None or not valid:
        logger.info("login_failed", email=email)
        raise AuthError("Incorrect email or password.")

    try:
        issued = create_access_token(user.id, settings)
    except TokenError as exc:  # pragma: no cover - guarded by the secret check above
        raise AuthConfigurationError(str(exc)) from exc

    logger.info("login_succeeded", user_id=str(user.id))
    return IssuedToken(
        token=issued.token, expires_in=issued.expires_in, expires_at=issued.expires_at
    )
