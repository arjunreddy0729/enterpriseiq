"""POST /api/v1/auth/token - exchange a password for an access token."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import IdentityDep, SessionDep, SettingsDep
from app.api.errors import ConfigurationError
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.rate_limit import login_limit
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    TokenError,
    create_access_token,
    verify_password,
)
from app.db.models import User
from app.schemas.auth import LoginRequest, MeResponse, TokenResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_BAD_CREDENTIALS = "Incorrect email or password."


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Log in with email and password (JSON)",
    responses={401: {"description": "Incorrect email or password"}},
    dependencies=[Depends(login_limit)],
)
def issue_token(payload: LoginRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    return _authenticate(session, settings, payload.email, payload.password)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in with email and password (OAuth2 form, used by the Authorize button)",
    responses={401: {"description": "Incorrect email or password"}},
    dependencies=[Depends(login_limit)],
)
def oauth_login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    """The same login, in the form-encoded shape OAuth2's password flow uses.
    This is what the Authorize dialog in /docs calls; `username` is the email."""
    return _authenticate(session, settings, form.username, form.password)


def _authenticate(session: Session, settings: Settings, email: str, password: str) -> TokenResponse:
    if settings.jwt_secret is None:
        raise ConfigurationError("JWT_SECRET is not configured, so tokens cannot be issued.")

    email = email.strip().lower()
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()

    # Verify against a dummy hash for unknown emails so both failures take the
    # same time, and return the same message for both, so neither the body nor
    # the latency reveals which emails have accounts.
    stored = user.password_hash if user is not None else None
    valid = verify_password(password, stored or DUMMY_PASSWORD_HASH)
    if user is None or stored is None or not valid:
        logger.info("login_failed", email=email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BAD_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        issued = create_access_token(user.id, settings)
    except TokenError as exc:  # pragma: no cover - guarded by the secret check above
        raise ConfigurationError(str(exc)) from exc

    logger.info("login_succeeded", user_id=str(user.id))
    return TokenResponse(
        access_token=issued.token, expires_in=issued.expires_in, expires_at=issued.expires_at
    )


@router.get("/me", response_model=MeResponse, summary="The caller and their current groups")
def me(identity: IdentityDep) -> MeResponse:
    return MeResponse(
        user_id=identity.user_id,
        email=identity.email,
        name=identity.name,
        role=identity.role,
        groups=list(identity.group_names),
    )
