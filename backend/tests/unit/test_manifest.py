"""Corpus manifest validation.

The manifest is the reproducible definition of the demo corpus AND its
permission topology. If it drifts from what is on disk, every permission test
and every evaluation number downstream becomes meaningless - so it gets its
own test suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic import ValidationError

from app.ingestion.manifest import (
    CorpusManifest,
    ManifestError,
    load_manifest,
    verify_files_exist,
)


class TestRealManifest:
    def test_manifest_parses(self, manifest: CorpusManifest) -> None:
        assert manifest.version == 1
        assert manifest.company.startswith("Northwind")
        assert len(manifest.documents) >= 20

    def test_every_declared_document_exists_on_disk(
        self, manifest: CorpusManifest, corpus_dir: Path
    ) -> None:
        missing = verify_files_exist(manifest, corpus_dir)
        assert missing == [], f"manifest lists files that do not exist: {missing}"

    def test_every_file_on_disk_is_declared(
        self, manifest: CorpusManifest, corpus_dir: Path
    ) -> None:
        # The reverse direction matters just as much: an undeclared file would
        # be ingested with no ACL, or silently skipped.
        declared = {doc.path for doc in manifest.documents}
        on_disk = {
            str(p.relative_to(corpus_dir))
            for p in corpus_dir.rglob("*")
            if p.is_file() and p.name != "manifest.yaml"
        }
        assert on_disk - declared == set(), "files on disk are missing from the manifest"

    def test_expected_groups_are_declared(self, manifest: CorpusManifest) -> None:
        assert set(manifest.groups) == {
            "all-employees",
            "engineering",
            "hr",
            "finance",
            "legal",
        }

    def test_all_four_departments_are_represented(self, manifest: CorpusManifest) -> None:
        departments = {doc.department for doc in manifest.documents}
        assert {"engineering", "hr", "finance", "legal"} <= departments

    def test_corpus_covers_more_than_one_file_format(self, manifest: CorpusManifest) -> None:
        # The chunker has to survive both Markdown structure and flat text.
        assert {"markdown", "txt"} <= {doc.source_type for doc in manifest.documents}


class TestPermissionTopology:
    """These assertions ARE the permission demo. If they stop holding, the
    permission-negative evaluation cases are no longer testing anything."""

    def test_there_are_documents_no_ordinary_employee_can_read(
        self, manifest: CorpusManifest
    ) -> None:
        restricted = manifest.restricted_documents()
        assert len(restricted) >= 4

    def test_compensation_policy_is_hr_only(self, manifest: CorpusManifest) -> None:
        doc = manifest.by_path("hr/compensation-policy.md")
        assert doc is not None
        assert doc.access_groups == ["hr"]
        assert doc.classification == "restricted"

    def test_an_engineer_cannot_see_hr_restricted_documents(self, manifest: CorpusManifest) -> None:
        engineer_groups = {"engineering", "all-employees"}
        visible = {d.path for d in manifest.documents_for_groups(engineer_groups)}
        assert "hr/compensation-policy.md" not in visible
        assert "hr/performance-review-process.md" not in visible
        # ... but company-wide HR policy is fine.
        assert "hr/leave-policy.md" in visible

    def test_hr_can_see_hr_restricted_documents(self, manifest: CorpusManifest) -> None:
        hr_groups = {"hr", "all-employees"}
        visible = {d.path for d in manifest.documents_for_groups(hr_groups)}
        assert "hr/compensation-policy.md" in visible

    def test_multi_group_user_sees_the_union(self, manifest: CorpusManifest) -> None:
        # Sofia Reyes is in engineering AND finance: this exercises array
        # overlap rather than single-group matching.
        sofia = {"engineering", "finance", "all-employees"}
        visible = {d.path for d in manifest.documents_for_groups(sofia)}
        assert "engineering/authentication.md" in visible
        assert "finance/procurement-thresholds.md" in visible
        assert "hr/compensation-policy.md" not in visible

    def test_a_two_group_document_is_visible_to_either_group(
        self, manifest: CorpusManifest
    ) -> None:
        doc = manifest.by_path("legal/vendor-policy.md")
        assert doc is not None
        assert set(doc.access_groups) == {"legal", "finance"}
        for groups in ({"legal"}, {"finance"}):
            assert doc in manifest.documents_for_groups(groups)

    def test_every_engineering_document_is_engineering_scoped(
        self, manifest: CorpusManifest
    ) -> None:
        for doc in manifest.documents:
            if doc.department == "engineering":
                assert "engineering" in doc.access_groups, doc.path

    def test_restricted_classification_never_reaches_all_employees(
        self, manifest: CorpusManifest
    ) -> None:
        for doc in manifest.documents:
            if doc.classification == "restricted":
                assert "all-employees" not in doc.access_groups, doc.path


class TestValidation:
    """The manifest loader must reject bad input loudly, not silently."""

    BASE: ClassVar[dict[str, Any]] = {
        "version": 1,
        "company": "Test Co",
        "groups": ["all-employees", "engineering"],
        "documents": [
            {
                "path": "engineering/a.md",
                "title": "A",
                "source_type": "markdown",
                "department": "engineering",
                "doc_type": "architecture",
                "owner": "a@example.test",
                "access_groups": ["engineering"],
            }
        ],
    }

    def test_valid_minimal_manifest(self) -> None:
        assert CorpusManifest.model_validate(self.BASE).documents[0].classification == "internal"

    def test_undeclared_access_group_is_rejected(self) -> None:
        data = {**self.BASE, "documents": [{**self.BASE["documents"][0], "access_groups": ["ops"]}]}  # type: ignore[index]
        with pytest.raises(ValidationError, match="undeclared group"):
            CorpusManifest.model_validate(data)

    def test_duplicate_paths_are_rejected(self) -> None:
        doc = self.BASE["documents"][0]  # type: ignore[index]
        with pytest.raises(ValidationError, match="duplicate document path"):
            CorpusManifest.model_validate({**self.BASE, "documents": [doc, dict(doc)]})

    def test_extension_must_match_source_type(self) -> None:
        data = {
            **self.BASE,
            "documents": [{**self.BASE["documents"][0], "source_type": "txt"}],  # type: ignore[index]
        }
        with pytest.raises(ValidationError, match="implies source_type"):
            CorpusManifest.model_validate(data)

    def test_path_traversal_is_rejected(self) -> None:
        data = {
            **self.BASE,
            "documents": [{**self.BASE["documents"][0], "path": "../../etc/passwd"}],  # type: ignore[index]
        }
        with pytest.raises(ValidationError, match="must not escape"):
            CorpusManifest.model_validate(data)

    def test_empty_access_groups_is_rejected(self) -> None:
        # A document with no groups would be unreachable by everyone, which is
        # almost certainly an authoring mistake rather than an intent.
        data = {
            **self.BASE,
            "documents": [{**self.BASE["documents"][0], "access_groups": []}],  # type: ignore[index]
        }
        with pytest.raises(ValidationError):
            CorpusManifest.model_validate(data)

    def test_unknown_top_level_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CorpusManifest.model_validate({**self.BASE, "typo_key": True})

    def test_missing_file_raises_manifest_error(self, tmp_path: Path) -> None:
        with pytest.raises(ManifestError, match="not found"):
            load_manifest(tmp_path / "nope.yaml")

    def test_invalid_yaml_raises_manifest_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "manifest.yaml"
        bad.write_text("groups: [unclosed\n", encoding="utf-8")
        with pytest.raises(ManifestError, match="not valid YAML"):
            load_manifest(bad)
