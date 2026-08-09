"""Corpus manifest loading and validation.

`corpus/manifest.yaml` declares, for every document in the demo corpus, its
metadata and - critically - its access groups. It is what makes the permission
topology reproducible: anyone who clones this repo and runs the ingest script
gets the exact same documents with the exact same ACLs, so the permission
tests and the evaluation benchmark mean the same thing on their machine as on
ours.

Parsing is deterministic Python with Pydantic validation. There is no reason
for a model to be anywhere near this.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SourceType = Literal["markdown", "txt", "pdf", "docx", "github"]
Classification = Literal["public", "internal", "confidential", "restricted"]
DocumentStatus = Literal["active", "superseded", "deleted"]

# Maps a file extension to the parser we will dispatch on. Kept here so the
# manifest can be validated before any parser exists.
EXTENSION_TO_SOURCE_TYPE: dict[str, SourceType] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
    ".pdf": "pdf",
    ".docx": "docx",
}


class ManifestError(ValueError):
    """Raised when the manifest is structurally valid YAML but semantically wrong."""


class DocumentEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Path relative to the corpus directory")
    title: str
    source_type: SourceType
    department: str
    doc_type: str
    owner: str
    classification: Classification = "internal"
    access_groups: list[str] = Field(min_length=1)
    effective_date: dt.date | None = None
    source_updated_at: dt.datetime | None = None
    status: DocumentStatus = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        if value.startswith("/") or ".." in Path(value).parts:
            raise ValueError(f"path must be relative and must not escape the corpus: {value!r}")
        return value

    @model_validator(mode="after")
    def _extension_matches_source_type(self) -> DocumentEntry:
        suffix = Path(self.path).suffix.lower()
        expected = EXTENSION_TO_SOURCE_TYPE.get(suffix)
        if expected is not None and expected != self.source_type:
            raise ValueError(
                f"{self.path}: extension {suffix} implies source_type "
                f"{expected!r}, manifest says {self.source_type!r}"
            )
        return self

    @model_validator(mode="after")
    def _dedupe_access_groups(self) -> DocumentEntry:
        if len(set(self.access_groups)) != len(self.access_groups):
            raise ValueError(f"{self.path}: duplicate entries in access_groups")
        return self


class CorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    company: str
    description: str | None = None
    groups: list[str] = Field(min_length=1)
    documents: list[DocumentEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_references(self) -> CorpusManifest:
        known = set(self.groups)
        if len(known) != len(self.groups):
            raise ValueError("duplicate entries in groups")

        seen_paths: set[str] = set()
        for doc in self.documents:
            if doc.path in seen_paths:
                raise ValueError(f"duplicate document path: {doc.path}")
            seen_paths.add(doc.path)

            unknown = set(doc.access_groups) - known
            if unknown:
                raise ValueError(
                    f"{doc.path}: access_groups references undeclared group(s) "
                    f"{sorted(unknown)}; declare them under `groups:`"
                )
        return self

    # --- Convenience accessors --------------------------------------------
    def by_path(self, path: str) -> DocumentEntry | None:
        return next((d for d in self.documents if d.path == path), None)

    def restricted_documents(self) -> list[DocumentEntry]:
        """Documents NOT readable by the all-employees group.

        These are the ones the permission tests and the permission-negative
        evaluation cases are built around.
        """
        return [d for d in self.documents if "all-employees" not in d.access_groups]

    def documents_for_groups(self, groups: set[str]) -> list[DocumentEntry]:
        """Exactly what a user in `groups` is allowed to see.

        This mirrors the SQL predicate `chunks.access_group_ids && :user_groups`
        and exists so tests can assert the database agrees with the manifest.
        """
        return [d for d in self.documents if groups & set(d.access_groups)]


def load_manifest(path: Path) -> CorpusManifest:
    """Parse and validate a manifest file."""
    if not path.exists():
        raise ManifestError(f"manifest not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManifestError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError(f"{path}: expected a mapping at the top level")
    return CorpusManifest.model_validate(raw)


def verify_files_exist(manifest: CorpusManifest, corpus_dir: Path) -> list[str]:
    """Return the manifest paths that do not exist on disk (empty == all good)."""
    return [doc.path for doc in manifest.documents if not (corpus_dir / doc.path).is_file()]
