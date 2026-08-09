"""Seed the access-control identities for the demo corpus.

Idempotent: safe to run on every container start. Groups are matched by name
and users by email, so re-running updates rather than duplicates.

The group membership here is the whole point of the permission demo:

  Priya (engineering)  asks "what is our compensation policy?"
      -> compensation-policy.md is [hr] only
      -> zero chunks survive the ACL predicate
      -> the system abstains, and nothing restricted ever reaches the model.

  Marcus (hr) asks the identical question and gets a cited answer.

  Sofia is in BOTH engineering and finance, which exercises the array-overlap
  path rather than the single-group path.

Run:  python -m scripts.seed_users
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.models import Group, User, UserGroup
from app.db.session import SessionLocal

logger = get_logger(__name__)


@dataclass(frozen=True)
class GroupSeed:
    name: str
    description: str


@dataclass(frozen=True)
class UserSeed:
    email: str
    name: str
    department: str
    title: str
    groups: list[str] = field(default_factory=list)
    role: str = "employee"


GROUPS: list[GroupSeed] = [
    GroupSeed("all-employees", "Every Northwind employee. Company-wide policies."),
    GroupSeed("engineering", "Engineering organisation: platform, payments, infrastructure."),
    GroupSeed("hr", "People Operations. Owns compensation and performance data."),
    GroupSeed("finance", "Finance and accounting. Owns procurement and revenue policy."),
    GroupSeed("legal", "Legal and privacy. Owns retention, vendor and incident policy."),
]

USERS: list[UserSeed] = [
    UserSeed(
        email="priya.raman@northwind.example",
        name="Priya Raman",
        department="engineering",
        title="Staff Engineer, Platform",
        groups=["engineering", "all-employees"],
    ),
    UserSeed(
        email="dev.shah@northwind.example",
        name="Dev Shah",
        department="engineering",
        title="Senior Engineer, Payments",
        groups=["engineering", "all-employees"],
    ),
    UserSeed(
        # Deliberately in two departments: exercises the array-overlap ACL path.
        email="sofia.reyes@northwind.example",
        name="Sofia Reyes",
        department="engineering",
        title="Engineering Manager, Infrastructure",
        groups=["engineering", "finance", "all-employees"],
    ),
    UserSeed(
        email="marcus.webb@northwind.example",
        name="Marcus Webb",
        department="hr",
        title="Director of People Operations",
        groups=["hr", "all-employees"],
    ),
    UserSeed(
        email="dana.okafor@northwind.example",
        name="Dana Okafor",
        department="finance",
        title="Controller",
        groups=["finance", "all-employees"],
    ),
    UserSeed(
        email="tom.lindqvist@northwind.example",
        name="Tom Lindqvist",
        department="legal",
        title="General Counsel",
        groups=["legal", "all-employees"],
    ),
    UserSeed(
        email="admin@northwind.example",
        name="Platform Admin",
        department="engineering",
        title="EnterpriseIQ Administrator",
        groups=["all-employees", "engineering", "hr", "finance", "legal"],
        role="admin",
    ),
]


def seed_groups(session: Session) -> dict[str, Group]:
    existing = {g.name: g for g in session.scalars(select(Group)).all()}
    for spec in GROUPS:
        group = existing.get(spec.name)
        if group is None:
            group = Group(name=spec.name, description=spec.description)
            session.add(group)
            existing[spec.name] = group
            logger.info("group_created", name=spec.name)
        elif group.description != spec.description:
            group.description = spec.description
            logger.info("group_updated", name=spec.name)
    session.flush()
    return existing


def seed_users(session: Session, groups: dict[str, Group]) -> None:
    existing = {u.email: u for u in session.scalars(select(User)).all()}

    for spec in USERS:
        user = existing.get(spec.email)
        if user is None:
            user = User(
                email=spec.email,
                name=spec.name,
                role=spec.role,
                department=spec.department,
                title=spec.title,
            )
            session.add(user)
            session.flush()
            logger.info("user_created", email=spec.email)
        else:
            user.name = spec.name
            user.role = spec.role
            user.department = spec.department
            user.title = spec.title

        desired_ids = {groups[name].id for name in spec.groups}
        current_ids = set(
            session.scalars(select(UserGroup.group_id).where(UserGroup.user_id == user.id)).all()
        )

        for group_id in desired_ids - current_ids:
            session.add(UserGroup(user_id=user.id, group_id=group_id))
        for group_id in current_ids - desired_ids:
            membership = session.get(UserGroup, {"user_id": user.id, "group_id": group_id})
            if membership is not None:
                session.delete(membership)

        if desired_ids != current_ids:
            logger.info("user_groups_synced", email=spec.email, groups=sorted(spec.groups))

    session.flush()


def print_summary(session: Session) -> None:
    users = session.scalars(select(User).order_by(User.email)).all()
    width = max(len(u.email) for u in users)
    print()
    print("Seeded identities (use the email as the X-Dev-User header):")
    print("-" * (width + 46))
    for user in users:
        names = sorted(g.name for g in user.groups)
        print(f"  {user.email:<{width}}  {user.role:<8}  {', '.join(names)}")
    print("-" * (width + 46))
    print()


def main() -> int:
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)

    with SessionLocal() as session:
        try:
            groups = seed_groups(session)
            seed_users(session, groups)
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error("seed_failed", error=str(exc))
            raise
        print_summary(session)

    logger.info("seed_complete", groups=len(GROUPS), users=len(USERS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
