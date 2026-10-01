"""Changing who can read what, and recording that it changed.

Two kinds of change, both revocations in the worst case:

* **A document's groups.** `document_permissions` is the source of truth and
  `chunks.access_group_ids` is the copy the retrieval predicate reads. Both
  are rewritten in ONE transaction, together with the audit row. There is no
  window in which the permission table says "revoked" while the chunks still
  say "allowed", which is the window a background propagation job would open.
* **A user's groups.** Nothing to propagate: groups are resolved per request,
  so the next request after the commit already sees the new set, even with a
  token issued before the change.

Note for the demo corpus: `scripts.ingest_corpus` reconciles every document's
ACL back to `corpus/manifest.yaml`, which is the declarative definition of the
demo. An ACL changed here lasts until the next re-ingest.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.api.errors import InvalidRequestError, NotFoundError
from app.core.identity import Identity, IdentityError, resolve_group_ids
from app.core.logging import get_logger, request_id_var
from app.db.models import (
    Chunk,
    Document,
    DocumentPermission,
    Group,
    PermissionChange,
    User,
    UserGroup,
)

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DocumentAcl:
    document_id: uuid.UUID
    title: str
    source_uri: str
    classification: str
    groups: list[str]
    chunk_count: int


@dataclass(frozen=True, slots=True)
class UserAccess:
    user_id: uuid.UUID
    email: str
    name: str
    role: str
    groups: list[str]


class PermissionService:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------
    def list_documents(self) -> list[DocumentAcl]:
        documents = self._session.scalars(
            select(Document).where(Document.status == "active").order_by(Document.source_uri)
        ).all()
        return [self._document_acl(doc) for doc in documents]

    def get_document(self, document_id: uuid.UUID) -> DocumentAcl:
        return self._document_acl(self._load_document(document_id))

    def set_document_groups(
        self, document_id: uuid.UUID, group_names: list[str], actor: Identity
    ) -> DocumentAcl:
        """Replace a document's ACL, its chunks' copy, and log it, atomically."""
        document = self._load_document(document_id)
        names = _dedupe(group_names)
        if not names:
            # A document no group can read is invisible to every search and
            # cannot be found to be fixed. Delete it instead.
            raise InvalidRequestError("A document must stay readable by at least one group.")
        group_ids = self._group_ids(names)
        before = self._document_group_names(document.id)

        self._session.execute(
            delete(DocumentPermission).where(DocumentPermission.document_id == document.id)
        )
        self._session.add_all(
            DocumentPermission(document_id=document.id, group_id=gid) for gid in group_ids
        )
        self._session.execute(
            update(Chunk)
            .where(Chunk.document_id == document.id)
            .values(access_group_ids=sorted(group_ids))
        )
        self._record(
            actor,
            action="document_acl",
            target_id=str(document.id),
            target_label=document.source_uri,
            before=before,
            after=sorted(names),
        )
        self._session.commit()

        logger.info(
            "document_acl_changed",
            document=document.source_uri,
            before=before,
            after=sorted(names),
            actor=actor.email,
        )
        return self._document_acl(document)

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    def list_users(self) -> list[UserAccess]:
        users = self._session.scalars(select(User).order_by(User.email)).all()
        return [self._user_access(user) for user in users]

    def set_user_groups(
        self, user_id: uuid.UUID, group_names: list[str], actor: Identity
    ) -> UserAccess:
        """Replace a user's group memberships. An empty list is allowed: it is
        how someone is offboarded, and they then retrieve nothing."""
        user = self._session.get(User, user_id)
        if user is None:
            raise NotFoundError(f"No user with id {user_id}.")
        names = _dedupe(group_names)
        group_ids = self._group_ids(names) if names else []
        before = self._user_group_names(user.id)

        self._session.execute(delete(UserGroup).where(UserGroup.user_id == user.id))
        self._session.add_all(UserGroup(user_id=user.id, group_id=gid) for gid in group_ids)
        self._record(
            actor,
            action="user_groups",
            target_id=str(user.id),
            target_label=user.email,
            before=before,
            after=sorted(names),
        )
        self._session.commit()

        logger.info(
            "user_groups_changed",
            user=user.email,
            before=before,
            after=sorted(names),
            actor=actor.email,
        )
        return self._user_access(user)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _load_document(self, document_id: uuid.UUID) -> Document:
        document = self._session.get(Document, document_id)
        if document is None or document.status != "active":
            raise NotFoundError(f"No active document with id {document_id}.")
        return document

    def _group_ids(self, names: list[str]) -> list[int]:
        try:
            return resolve_group_ids(self._session, names)
        except IdentityError as exc:
            raise InvalidRequestError(str(exc)) from exc

    def _document_group_names(self, document_id: uuid.UUID) -> list[str]:
        return list(
            self._session.scalars(
                select(Group.name)
                .join(DocumentPermission, DocumentPermission.group_id == Group.id)
                .where(DocumentPermission.document_id == document_id)
                .order_by(Group.name)
            )
        )

    def _user_group_names(self, user_id: uuid.UUID) -> list[str]:
        return list(
            self._session.scalars(
                select(Group.name)
                .join(UserGroup, UserGroup.group_id == Group.id)
                .where(UserGroup.user_id == user_id)
                .order_by(Group.name)
            )
        )

    def _document_acl(self, document: Document) -> DocumentAcl:
        chunk_count = self._session.execute(
            select(func.count(Chunk.id)).where(Chunk.document_id == document.id)
        ).scalar_one()
        return DocumentAcl(
            document_id=document.id,
            title=document.title,
            source_uri=document.source_uri,
            classification=document.classification,
            groups=self._document_group_names(document.id),
            chunk_count=int(chunk_count),
        )

    def _user_access(self, user: User) -> UserAccess:
        return UserAccess(
            user_id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            groups=self._user_group_names(user.id),
        )

    def _record(
        self,
        actor: Identity,
        *,
        action: str,
        target_id: str,
        target_label: str,
        before: list[str],
        after: list[str],
    ) -> None:
        self._session.add(
            PermissionChange(
                actor_email=actor.email,
                action=action,
                target_id=target_id,
                target_label=target_label,
                before=before,
                after=after,
                request_id=request_id_var.get(),
            )
        )


def _dedupe(names: list[str]) -> list[str]:
    return list(dict.fromkeys(name.strip() for name in names if name.strip()))
