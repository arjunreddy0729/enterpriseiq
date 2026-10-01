"""Request and response models for /api/v1/auth."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the token expires.")
    expires_at: dt.datetime


class MeResponse(BaseModel):
    """Who the token belongs to and what they can read right now.

    Groups are looked up at request time, so this reflects any change made
    since the token was issued.
    """

    user_id: uuid.UUID
    email: str
    name: str
    role: str
    groups: list[str]
