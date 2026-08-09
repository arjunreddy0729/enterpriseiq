"""Response models for the health endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["ok", "degraded", "fail"]


class ComponentCheck(BaseModel):
    """Result of one readiness probe."""

    name: str = Field(description="Component being checked, e.g. 'database'")
    status: CheckStatus
    detail: str | None = Field(
        default=None, description="Human-readable explanation, present when not 'ok'"
    )


class LivenessResponse(BaseModel):
    """/healthz - is the process up? Deliberately checks no dependencies."""

    status: Literal["healthy"] = "healthy"
    app: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    """/readyz - can this process actually serve traffic?"""

    status: Literal["ready", "not_ready"]
    app: str
    version: str
    checks: list[ComponentCheck]
