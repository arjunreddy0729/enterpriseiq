"""FastAPI dependencies.

Identity resolution lives here so that every protected route gets it the same
way. Authentication (who are you?) and authorisation (what may you read?) are
kept apart: whichever way the caller proves who they are, the groups that end
up in the retrieval predicate come from the same database lookup.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.api.errors import PermissionDeniedError
from app.core.config import Settings, get_settings
from app.core.identity import (
    DEV_USER_HEADER,
    Identity,
    IdentityError,
    resolve_identity,
    resolve_identity_by_id,
)
from app.core.security import TokenError, decode_access_token
from app.db.session import get_session
from app.retrieval.embedder import get_embedder
from app.retrieval.ports import Embedder

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

# OAuth2's password flow is what gives /docs an Authorize dialog with email and
# password fields, so a visitor never copies a token by hand. On the wire it is
# still just `Authorization: Bearer <jwt>`, which is all this reads.
_bearer = OAuth2PasswordBearer(
    tokenUrl=f"{get_settings().api_v1_prefix}/auth/login",
    auto_error=False,
    description="Log in with a demo email as the username.",
)


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_identity(
    session: SessionDep,
    settings: SettingsDep,
    token: Annotated[str | None, Depends(_bearer)] = None,
    x_dev_user: Annotated[
        str | None,
        Header(
            alias=DEV_USER_HEADER,
            # Hidden from /docs: it is a curl convenience, and an empty text box
            # above the request body is where people paste their question.
            include_in_schema=False,
            description=(
                "Local development only: the email of a seeded user, no password. "
                "Disabled when AUTH_DEV_HEADER_ENABLED=false and always in production."
            ),
        ),
    ] = None,
) -> Identity:
    """Resolve the caller, or refuse the request.

    A bearer token wins over the dev header when both are sent. An
    unidentified caller is rejected with 401 rather than treated as a user
    with no groups: both would return zero results, but only one of them
    tells the truth about why.
    """
    try:
        if token is not None:
            user_id = decode_access_token(token, settings)
            return resolve_identity_by_id(session, user_id)
        if x_dev_user and settings.auth_dev_header_enabled:
            return resolve_identity(session, x_dev_user)
    except (TokenError, IdentityError) as exc:
        raise _unauthorised(str(exc)) from exc

    raise _unauthorised("Not authenticated. Send 'Authorization: Bearer <token>'.")


IdentityDep = Annotated[Identity, Depends(current_identity)]


def admin_identity(identity: IdentityDep) -> Identity:
    """Admins only. Checked against the role in the database, per request."""
    if not identity.is_admin:
        raise PermissionDeniedError("This endpoint requires the admin role.")
    return identity


def writable_admin(
    admin: Annotated[Identity, Depends(admin_identity)], settings: SettingsDep
) -> Identity:
    """Admin endpoints that change permissions. Off in the public demo, where
    the admin login is shared and one visitor's change would be every
    visitor's broken demo. Reading permissions and the audit trail stays on."""
    if settings.demo_mode:
        raise PermissionDeniedError(
            "Changing permissions is disabled in the public demo, where everyone shares "
            "the admin login. Run it locally (docker compose up) to try revocation."
        )
    return admin


def embedder() -> Embedder:
    return get_embedder()


AdminDep = Annotated[Identity, Depends(admin_identity)]
WritableAdminDep = Annotated[Identity, Depends(writable_admin)]
EmbedderDep = Annotated[Embedder, Depends(embedder)]
