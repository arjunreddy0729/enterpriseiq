"""Answering "who saw this?" and "who changed that?" from the logs.

`query_logs.retrieved_document_ids` records every document whose text left
the database for a request, cited or not, behind a GIN index. So "who
retrieved the compensation policy in the last 30 days" is one indexed
array-containment lookup:

    WHERE retrieved_document_ids @> ARRAY[:document_id]
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import NotFoundError
from app.db.models import Document, PermissionChange, QueryLog, User


@dataclass(frozen=True, slots=True)
class AccessEvent:
    request_id: str
    created_at: dt.datetime
    user_email: str | None
    endpoint: str
    query: str
    status: str
    shown_to_user: bool


class AuditService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def document_access(
        self, document_id: uuid.UUID, *, days: int, limit: int
    ) -> list[AccessEvent]:
        document = self._session.get(Document, document_id)
        if document is None:
            raise NotFoundError(f"No document with id {document_id}.")

        since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
        rows = self._session.execute(
            select(QueryLog, User.email)
            .outerjoin(User, User.id == QueryLog.user_id)
            .where(QueryLog.retrieved_document_ids.contains([document_id]))
            .where(QueryLog.created_at >= since)
            .order_by(QueryLog.created_at.desc())
            .limit(limit)
        ).all()

        return [
            AccessEvent(
                request_id=log.request_id,
                created_at=log.created_at,
                user_email=email,
                endpoint=log.endpoint,
                query=log.query,
                status=log.status,
                shown_to_user=_shown_to_user(log, document.source_uri),
            )
            for log, email in rows
        ]

    def permission_changes(self, *, limit: int) -> list[PermissionChange]:
        return list(
            self._session.scalars(
                select(PermissionChange).order_by(PermissionChange.created_at.desc()).limit(limit)
            )
        )


def _shown_to_user(log: QueryLog, source_uri: str) -> bool:
    """/search returns passages verbatim, so everything it retrieved was shown.
    /query only shows the passages it cites; the rest reached the model's
    context but not the caller."""
    if log.endpoint == "search":
        return True
    return any(c.get("source_uri") == source_uri for c in (log.citations or []))
