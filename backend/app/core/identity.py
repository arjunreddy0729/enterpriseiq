"""Who is asking, and what may they read.

Authentication is a password exchanged for a short-lived JWT (see
app/core/security.py). Local development also accepts `X-Dev-User: <email>`,
which production refuses to start with.

Authorisation is the part that matters, and it is real. The groups resolved
here flow into every RetrievalQuery and end up as a SQL predicate. Swapping
the authentication mechanism does not touch that path at all, which is the
point of keeping the two separate: the interesting property of this system is
that a user cannot retrieve what they cannot read, and that property does not
depend on how they proved who they are.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Group, User, UserGroup

DEV_USER_HEADER = "X-Dev-User"


class IdentityError(Exception):
    """Raised when a caller cannot be identified."""


@dataclass(frozen=True, slots=True)
class Identity:
    """An authenticated caller and their resolved access groups."""

    user_id: uuid.UUID
    email: str
    name: str
    role: str
    group_ids: tuple[int, ...]
    group_names: tuple[str, ...]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def resolve_identity(session: Session, email: str) -> Identity:
    """Look up a user and their groups.

    Raises IdentityError for an unknown user rather than returning an
    anonymous identity. A caller we cannot identify has no groups, and a
    request with no groups must be rejected at the door rather than quietly
    retrieving nothing - the two are indistinguishable to the user otherwise,
    and "your search found nothing" is a bad way to say "you are not logged
    in".
    """
    normalised = (email or "").strip().lower()
    if not normalised:
        raise IdentityError("no identity supplied")

    user = session.execute(select(User).where(User.email == normalised)).scalar_one_or_none()
    if user is None:
        raise IdentityError(f"unknown user: {normalised}")
    return identity_for(session, user)


def resolve_identity_by_id(session: Session, user_id: uuid.UUID) -> Identity:
    """Resolve the subject of a verified token.

    Groups are read here, at request time, not from the token. A user removed
    from a group loses that group's documents on their next request even while
    holding a token issued before the change.
    """
    user = session.get(User, user_id)
    if user is None:
        raise IdentityError("token subject no longer exists")
    return identity_for(session, user)


def identity_for(session: Session, user: User) -> Identity:
    """Build an Identity with the user's current groups."""
    rows = session.execute(
        select(Group.id, Group.name)
        .join(UserGroup, UserGroup.group_id == Group.id)
        .where(UserGroup.user_id == user.id)
        .order_by(Group.name)
    ).all()

    return Identity(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        group_ids=tuple(row.id for row in rows),
        group_names=tuple(row.name for row in rows),
    )


def resolve_group_ids(session: Session, names: list[str]) -> list[int]:
    """Map group names to ids. Unknown names are an error, not a silent skip.

    Silently dropping an unknown group name during ingestion would produce a
    document that is less readable than the manifest says - or, if every name
    were dropped, one readable by nobody. Both are the kind of failure that
    surfaces weeks later as "why can't anyone find this?".
    """
    rows = session.execute(select(Group.id, Group.name).where(Group.name.in_(names))).all()
    found = {row.name: row.id for row in rows}
    missing = sorted(set(names) - set(found))
    if missing:
        raise IdentityError(f"unknown group(s): {missing}")
    return [found[name] for name in names]
