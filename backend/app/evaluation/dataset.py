"""Benchmark dataset loading and validation.

The dataset is validated against the corpus manifest at load time, so a
question referencing a document that no longer exists fails immediately rather
than quietly scoring zero recall forever.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Category(StrEnum):
    FACTOID = "factoid"
    MULTI_HOP = "multi_hop"
    PERMISSION_NEGATIVE = "permission_negative"
    UNANSWERABLE = "unanswerable"


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: Category
    question: str
    asked_by: str

    #: Documents that should be retrieved. Empty for unanswerable questions.
    expected_sources: list[str] = Field(default_factory=list)
    #: Documents that must NOT be retrieved - the permission cases.
    forbidden_sources: list[str] = Field(default_factory=list)
    #: Values the answer must contain; '|' separates acceptable alternatives.
    expected_facts: list[str] = Field(default_factory=list)
    must_abstain: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> EvalCase:
        if self.must_abstain and self.expected_facts:
            raise ValueError(
                f"{self.id}: a case that must abstain cannot also expect facts "
                "in the answer"
            )
        if not self.must_abstain and not self.expected_sources:
            raise ValueError(f"{self.id}: an answerable case needs expected_sources")
        if self.category is Category.PERMISSION_NEGATIVE and not self.forbidden_sources:
            raise ValueError(
                f"{self.id}: a permission case must name the document that is "
                "being withheld, or it proves nothing"
            )
        return self


class EvalDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    corpus: str
    notes: list[str] = Field(default_factory=list)
    cases: list[EvalCase]

    @model_validator(mode="after")
    def _unique_ids(self) -> EvalDataset:
        seen = set()
        for case in self.cases:
            if case.id in seen:
                raise ValueError(f"duplicate case id: {case.id}")
            seen.add(case.id)
        return self

    def by_category(self, category: Category) -> list[EvalCase]:
        return [c for c in self.cases if c.category is category]

    @property
    def counts(self) -> dict[str, int]:
        return {c.value: len(self.by_category(c)) for c in Category}


def load_dataset(path: Path) -> EvalDataset:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return EvalDataset.model_validate(raw)


def validate_against_corpus(dataset: EvalDataset, manifest_paths: set[str]) -> list[str]:
    """Return problems where the dataset references documents that do not exist."""
    problems: list[str] = []
    for case in dataset.cases:
        for source in [*case.expected_sources, *case.forbidden_sources]:
            if source not in manifest_paths:
                problems.append(f"{case.id}: unknown document {source!r}")
    return problems
