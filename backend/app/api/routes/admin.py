"""/api/v1/admin - permission management and audit. Admin role only."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import AdminDep, SessionDep, SettingsDep, WritableAdminDep
from app.schemas.admin import (
    AccessEventOut,
    DocumentAccessReport,
    DocumentAclOut,
    GroupsUpdate,
    PermissionChangeOut,
    UserAccessOut,
)
from app.services.audit_service import AccessEvent, AuditService
from app.services.permission_service import PermissionService

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
@router.get("/documents", response_model=list[DocumentAclOut], summary="Documents and their ACLs")
def list_documents(session: SessionDep, _admin: AdminDep) -> list[DocumentAclOut]:
    return [DocumentAclOut(**asdict(d)) for d in PermissionService(session).list_documents()]


@router.get("/documents/{document_id}/permissions", response_model=DocumentAclOut)
def get_document_permissions(
    document_id: uuid.UUID, session: SessionDep, _admin: AdminDep
) -> DocumentAclOut:
    return DocumentAclOut(**asdict(PermissionService(session).get_document(document_id)))


@router.put(
    "/documents/{document_id}/permissions",
    response_model=DocumentAclOut,
    summary="Replace a document's groups (takes effect on the next query)",
)
def set_document_permissions(
    document_id: uuid.UUID, payload: GroupsUpdate, session: SessionDep, admin: WritableAdminDep
) -> DocumentAclOut:
    acl = PermissionService(session).set_document_groups(document_id, payload.groups, admin)
    return DocumentAclOut(**asdict(acl))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@router.get("/users", response_model=list[UserAccessOut], summary="Users and their groups")
def list_users(session: SessionDep, _admin: AdminDep) -> list[UserAccessOut]:
    return [UserAccessOut(**asdict(u)) for u in PermissionService(session).list_users()]


@router.put(
    "/users/{user_id}/groups",
    response_model=UserAccessOut,
    summary="Replace a user's groups (takes effect on their next request)",
)
def set_user_groups(
    user_id: uuid.UUID, payload: GroupsUpdate, session: SessionDep, admin: WritableAdminDep
) -> UserAccessOut:
    access = PermissionService(session).set_user_groups(user_id, payload.groups, admin)
    return UserAccessOut(**asdict(access))


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
@router.get(
    "/audit/documents/{document_id}",
    response_model=DocumentAccessReport,
    summary="Who retrieved this document",
)
def document_access(
    document_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    _admin: AdminDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> DocumentAccessReport:
    acl = PermissionService(session).get_document(document_id)
    events = AuditService(session).document_access(document_id, days=days, limit=limit)
    return DocumentAccessReport(
        document_id=document_id,
        source_uri=acl.source_uri,
        days=days,
        event_count=len(events),
        events=[_present(e, hide_query=settings.demo_mode) for e in events],
    )


#: In the public demo the admin login is shared, so the audit trail would
#: otherwise show every visitor what every other visitor typed.
HIDDEN_QUERY = "[hidden in the public demo]"


def _present(event: AccessEvent, *, hide_query: bool) -> AccessEventOut:
    out = AccessEventOut(**asdict(event))
    if hide_query:
        out.query = HIDDEN_QUERY
    return out


@router.get(
    "/audit/permission-changes",
    response_model=list[PermissionChangeOut],
    summary="History of ACL and group changes, newest first",
)
def permission_changes(
    session: SessionDep,
    _admin: AdminDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[PermissionChangeOut]:
    return [
        PermissionChangeOut.model_validate(change)
        for change in AuditService(session).permission_changes(limit=limit)
    ]
