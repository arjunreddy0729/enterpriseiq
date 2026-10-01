"""Request and response models for /api/v1/admin."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class GroupsUpdate(BaseModel):
    """The complete new set of groups. Replaces, never merges, so the request
    body states the end result and a retry is harmless."""

    model_config = ConfigDict(extra="forbid")

    groups: list[str] = Field(max_length=50)


class DocumentAclOut(BaseModel):
    document_id: uuid.UUID
    title: str
    source_uri: str
    classification: str
    groups: list[str]
    chunk_count: int


class UserAccessOut(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: str
    groups: list[str]


class AccessEventOut(BaseModel):
    request_id: str
    created_at: dt.datetime
    user_email: str | None
    endpoint: str
    query: str
    status: str
    shown_to_user: bool = Field(
        description=(
            "True when the caller saw this document's text: always for /search, "
            "and for /query only when the answer cited it."
        )
    )


class DocumentAccessReport(BaseModel):
    document_id: uuid.UUID
    source_uri: str
    days: int
    event_count: int
    events: list[AccessEventOut]


class PermissionChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: dt.datetime
    actor_email: str
    action: str
    target_id: str
    target_label: str
    before: list[str]
    after: list[str]
    request_id: str | None
