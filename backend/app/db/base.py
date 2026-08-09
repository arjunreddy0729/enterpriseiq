"""Declarative base for all ORM models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared SQLAlchemy 2.0 declarative base.

    Importing this module (and app.db.models) is what populates
    Base.metadata - Alembic's env.py relies on that for autogenerate.
    """
