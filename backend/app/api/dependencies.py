"""FastAPI dependencies.

Identity resolution lives here so that every protected route gets it the same
way, and so that replacing the dev header with a JWT bearer token in V2 is a
change to one function rather than to every endpoint.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.identity import DEV_USER_HEADER, Identity, IdentityError, resolve_identity
from app.db.session import get_session
from app.retrieval.embedder import get_embedder
from app.retrieval.ports import Embedder

SessionDep = Annotated[Session, Depends(get_session)]


def current_identity(
    session: SessionDep,
    x_dev_user: Annotated[
        str | None,
        Header(
            alias=DEV_USER_HEADER,
            description=(
                "Development authentication: the email of a seeded user. "
                "Replaced by a JWT bearer token in V2 - the authorisation model "
                "behind it does not change."
            ),
        ),
    ] = None,
) -> Identity:
    """Resolve the caller, or refuse the request.

    An unidentified caller is rejected with 401 rather than treated as a user
    with no groups. Both would return zero results, but only one of them tells
    the truth about why.
    """
    if not x_dev_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                f"Missing {DEV_USER_HEADER} header. Send the email of a seeded "
                f"user, e.g. '{DEV_USER_HEADER}: priya.raman@northwind.example'."
            ),
        )
    try:
        return resolve_identity(session, x_dev_user)
    except IdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc


def embedder() -> Embedder:
    return get_embedder()


IdentityDep = Annotated[Identity, Depends(current_identity)]
EmbedderDep = Annotated[Embedder, Depends(embedder)]
