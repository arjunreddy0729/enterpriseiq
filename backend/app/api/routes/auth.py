"""POST /api/v1/auth/token - exchange a password for an access token."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.dependencies import IdentityDep, SessionDep, SettingsDep
from app.api.errors import ConfigurationError
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.rate_limit import login_limit
from app.schemas.auth import LoginRequest, MeResponse, TokenResponse
from app.services.auth_service import AuthConfigurationError, AuthError, authenticate

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


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
    """Adapt the service's result and errors to HTTP."""
    try:
        issued = authenticate(session, settings, email, password)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AuthConfigurationError as exc:
        raise ConfigurationError(str(exc)) from exc

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
