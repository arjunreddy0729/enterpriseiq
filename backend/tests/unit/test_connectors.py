"""The connector contract, and the GitHub connector's logic.

No network: the GitHub tests replace the one HTTP method with recorded
payloads. What is being tested is the mapping from a tree listing to
SourceDocuments - the filtering, the titles, the revision tokens and above all
the access groups - not whether urllib works.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from app.ingestion.connectors import (
    ConnectorError,
    GitHubConnector,
    LocalFolderConnector,
    SourceDocument,
)


# ---------------------------------------------------------------------------
# SourceDocument
# ---------------------------------------------------------------------------
def test_a_document_with_no_audience_is_refused() -> None:
    """The whole point of the contract: a source that has not decided who may
    read a document must fail at the boundary, not index it."""
    with pytest.raises(ConnectorError, match="access_groups"):
        SourceDocument(
            source_uri="x.md",
            title="x",
            source_type="markdown",
            access_groups=[],
            loader=lambda: b"hi",
        )


def test_a_document_with_no_content_source_is_refused() -> None:
    with pytest.raises(ConnectorError, match="local_path or loader"):
        SourceDocument(source_uri="x.md", title="x", source_type="markdown", access_groups=["eng"])


def test_materialise_hands_over_a_real_path_for_local_files(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text("# Hello", encoding="utf-8")
    doc = SourceDocument(
        source_uri="doc.md",
        title="d",
        source_type="markdown",
        access_groups=["eng"],
        local_path=path,
    )
    with doc.materialise() as p:
        assert p == path
    assert path.exists(), "a local file must not be deleted after use"


def test_materialise_writes_remote_bytes_with_the_right_suffix() -> None:
    doc = SourceDocument(
        source_uri="remote.md",
        title="r",
        source_type="markdown",
        access_groups=["eng"],
        loader=lambda: b"# Remote",
    )
    with doc.materialise() as p:
        # The suffix matters: parser dispatch is by extension, and a PDF
        # parsed as text is silently garbage rather than an error.
        assert p.suffix == ".md"
        assert p.read_text() == "# Remote"
        temp = p
    assert not temp.exists(), "the temporary file must be cleaned up"


# ---------------------------------------------------------------------------
# Local folder connector
# ---------------------------------------------------------------------------
def test_local_connector_reads_the_manifest() -> None:
    from app.core.config import get_settings

    corpus = get_settings().corpus_dir
    if not corpus.is_dir():
        pytest.skip("corpus not available")

    docs = list(LocalFolderConnector(corpus).fetch())
    assert len(docs) == 22
    assert all(d.access_groups for d in docs)
    assert all(d.revision for d in docs), "stat() is cheaper than hashing; use it"

    restricted = next(d for d in docs if d.source_uri == "hr/compensation-policy.md")
    assert restricted.access_groups == ["hr"]


def test_local_connector_name_is_stable() -> None:
    assert LocalFolderConnector(Path("/tmp")).name == "local-corpus"


# ---------------------------------------------------------------------------
# GitHub connector
# ---------------------------------------------------------------------------
TREE = {
    "truncated": False,
    "tree": [
        {"type": "blob", "path": "README.md", "sha": "aaa", "size": 100},
        {"type": "blob", "path": "docs/architecture.md", "sha": "bbb", "size": 200},
        {"type": "blob", "path": "docs/runbook.txt", "sha": "ccc", "size": 50},
        {"type": "blob", "path": "src/main.py", "sha": "ddd", "size": 900},
        {"type": "blob", "path": "assets/logo.png", "sha": "eee", "size": 4000},
        {"type": "tree", "path": "docs", "sha": "fff"},
        {"type": "blob", "path": "huge.md", "sha": "ggg", "size": 99_999_999},
    ],
}


def fake_connector(private: bool = False, **kwargs: Any) -> GitHubConnector:
    connector = GitHubConnector(repo="acme/docs", access_groups=["engineering"], **kwargs)

    def _get(path: str) -> Any:
        if path == "/repos/acme/docs":
            return {
                "default_branch": "main",
                "private": private,
                "pushed_at": "2026-05-01T10:00:00Z",
            }
        if path.startswith("/repos/acme/docs/git/trees/"):
            return TREE
        if path.startswith("/repos/acme/docs/git/blobs/"):
            return {"encoding": "base64", "content": base64.b64encode(b"# Body").decode()}
        raise AssertionError(f"unexpected call: {path}")

    connector._get = _get  # type: ignore[method-assign]
    return connector


def test_only_parseable_files_are_indexed() -> None:
    uris = [d.source_uri for d in fake_connector().fetch()]
    assert "github://acme/docs/README.md" in uris
    assert "github://acme/docs/docs/architecture.md" in uris
    assert "github://acme/docs/docs/runbook.txt" in uris
    # Source code and images read as prose are noise in the index.
    assert not any("main.py" in u for u in uris)
    assert not any("logo.png" in u for u in uris)


def test_oversized_files_are_skipped() -> None:
    assert not any("huge.md" in d.source_uri for d in fake_connector().fetch())


def test_include_filters_by_path_prefix() -> None:
    uris = [d.source_uri for d in fake_connector(include=("docs/",)).fetch()]
    assert len(uris) == 2
    assert all("/docs/" in u for u in uris)


def test_revision_is_the_git_blob_sha() -> None:
    """git's own content hash - exact, and free to compare."""
    doc = next(d for d in fake_connector().fetch() if d.source_uri.endswith("architecture.md"))
    assert doc.revision == "bbb"


def test_access_groups_are_applied_to_every_document() -> None:
    assert all(d.access_groups == ["engineering"] for d in fake_connector().fetch())


def test_repo_is_required_in_owner_name_form() -> None:
    with pytest.raises(ConnectorError, match="owner/name"):
        GitHubConnector(repo="justaname", access_groups=["engineering"])


def test_access_groups_are_required() -> None:
    with pytest.raises(ConnectorError, match="access_groups is required"):
        GitHubConnector(repo="acme/docs", access_groups=[])


def test_private_repo_mapped_company_wide_is_warned_about(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Not blocked - an operator may mean it - but it is the mapping most
    likely to be an accident, so it is said out loud."""
    connector = GitHubConnector(repo="acme/docs", access_groups=["all-employees"])

    def _get(path: str) -> Any:
        if path == "/repos/acme/docs":
            return {"default_branch": "main", "private": True, "pushed_at": None}
        return TREE

    connector._get = _get  # type: ignore[method-assign]
    list(connector.fetch())
    # structlog writes straight to stdout here rather than through stdlib
    # logging, so caplog never sees it; capsys does.
    assert "private_repo_mapped_company_wide" in capsys.readouterr().out


def test_nested_readmes_get_a_distinguishing_title() -> None:
    """A citation list full of files called README is unusable."""
    connector = GitHubConnector(repo="acme/docs", access_groups=["engineering"])

    def _get(path: str) -> Any:
        if path == "/repos/acme/docs":
            return {"default_branch": "main", "private": False, "pushed_at": None}
        return {
            "truncated": False,
            "tree": [
                {"type": "blob", "path": "services/payments/README.md", "sha": "x", "size": 10}
            ],
        }

    connector._get = _get  # type: ignore[method-assign]
    doc = next(iter(connector.fetch()))
    assert doc.title == "payments README"


def test_content_is_only_fetched_on_demand() -> None:
    """fetch() must not download anything: that is what makes an unchanged
    sync cost one listing instead of a download per file."""
    connector = GitHubConnector(repo="acme/docs", access_groups=["engineering"])
    calls: list[str] = []

    def _get(path: str) -> Any:
        calls.append(path)
        if path == "/repos/acme/docs":
            return {"default_branch": "main", "private": False, "pushed_at": None}
        if "/trees/" in path:
            return TREE
        return {"encoding": "base64", "content": base64.b64encode(b"# Body").decode()}

    connector._get = _get  # type: ignore[method-assign]
    docs = list(connector.fetch())
    assert not any("/blobs/" in c for c in calls), "fetch() downloaded content"

    with docs[0].materialise() as p:
        assert p.read_text() == "# Body"
    assert any("/blobs/" in c for c in calls)
