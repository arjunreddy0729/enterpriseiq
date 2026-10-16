"""Connector registry.

Adding a source is a new class satisfying the Connector protocol plus one line
here. Nothing downstream of SourceDocument changes.
"""

from __future__ import annotations

from app.ingestion.connectors.base import (
    Connector,
    ConnectorError,
    SourceDocument,
)
from app.ingestion.connectors.github import GitHubConnector
from app.ingestion.connectors.local import LocalFolderConnector

__all__ = [
    "Connector",
    "ConnectorError",
    "GitHubConnector",
    "LocalFolderConnector",
    "SourceDocument",
]
