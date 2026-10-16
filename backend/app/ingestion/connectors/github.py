"""Documentation in a GitHub repository.

Engineering knowledge lives in repos - READMEs, ADRs, runbooks, docs/ - and it
is the one enterprise source you can wire up without a tenant admin, which
makes it the right first real connector.

How it works:

    GET /repos/{repo}                      -> default branch, visibility
    GET /repos/{repo}/git/trees/HEAD       -> every file and its blob SHA, in
                                              ONE request, recursively
    GET /repos/{repo}/git/blobs/{sha}      -> content, only for files whose
                                              SHA we have not already stored

That shape matters. A repository with 2,000 documents costs two API calls to
list, and then one call per *changed* file. Syncing an unchanged repo is two
requests and zero downloads, which is what makes running it on a schedule
affordable. The blob SHA is git's own content hash, so it is exact rather than
a heuristic.

**On permissions.** GitHub's model is per-repository, not per-file: everyone
with read access to a repo can read every file in it. So the operator maps a
repo to groups, and this connector refuses to guess. It does read the repo's
visibility and warns when a private repo is mapped to a company-wide group,
because that is the mapping most likely to be a mistake rather than a choice.

Uses urllib from the standard library rather than adding an HTTP client to the
runtime dependencies for two API calls.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

from app.core.logging import get_logger
from app.ingestion.connectors.base import Connector, ConnectorError, SourceDocument

logger = get_logger(__name__)

_API = "https://api.github.com"
_TIMEOUT = 30

#: What we know how to parse. Everything else in the repo is ignored rather
#: than indexed as text, because a .py file read as prose is noise in the index.
_EXTENSIONS = {".md": "markdown", ".markdown": "markdown", ".txt": "txt"}

#: A group that, on a private repository, almost certainly means the operator
#: mapped the source too broadly.
_COMPANY_WIDE = "all-employees"


class GitHubConnector(Connector):
    """Markdown and text files from one repository."""

    def __init__(
        self,
        repo: str,
        access_groups: list[str],
        token: str | None = None,
        branch: str | None = None,
        include: tuple[str, ...] = (),
        department: str | None = None,
        doc_type: str = "documentation",
        classification: str = "internal",
        max_bytes: int = 1_000_000,
    ) -> None:
        if "/" not in repo:
            raise ConnectorError(f"repo must be 'owner/name', got {repo!r}")
        if not access_groups:
            raise ConnectorError(
                f"{repo}: access_groups is required. GitHub grants read access per "
                "repository, so the operator must say which groups that maps to."
            )
        self._repo = repo
        self._access_groups = list(access_groups)
        self._token = token
        self._branch = branch
        #: Path prefixes to include. Empty means the whole repository.
        self._include = include
        self._department = department
        self._doc_type = doc_type
        self._classification = classification
        self._max_bytes = max_bytes

    @property
    def name(self) -> str:
        return f"github:{self._repo}"

    # -- HTTP ---------------------------------------------------------------
    def _get(self, path: str) -> Any:
        request = urllib.request.Request(f"{_API}{path}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "EnterpriseIQ-connector")
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")

        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise ConnectorError(
                    f"{self._repo}: not found. A private repository needs a token with "
                    "read access; without one GitHub returns 404 rather than 403."
                ) from exc
            if exc.code == 403 and "rate limit" in str(exc.headers).lower():
                raise ConnectorError(
                    f"{self._repo}: GitHub rate limit reached. Unauthenticated requests "
                    "are capped at 60/hour; pass a token for 5,000."
                ) from exc
            raise ConnectorError(f"{self._repo}: GitHub returned {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ConnectorError(f"{self._repo}: could not reach GitHub: {exc.reason}") from exc

    # -- Connector ----------------------------------------------------------
    def fetch(self) -> Iterator[SourceDocument]:
        repo_info = self._get(f"/repos/{self._repo}")
        branch = self._branch or repo_info.get("default_branch") or "main"
        private = bool(repo_info.get("private"))

        if private and _COMPANY_WIDE in self._access_groups:
            # Not blocked: an operator may genuinely want a private repo
            # readable company-wide. But it is the mapping most likely to be
            # an accident, so it is said out loud.
            logger.warning(
                "private_repo_mapped_company_wide",
                repo=self._repo,
                groups=self._access_groups,
                detail="a private repository is being indexed as readable by everyone",
            )

        pushed_at = _parse_time(repo_info.get("pushed_at"))
        tree = self._get(f"/repos/{self._repo}/git/trees/{branch}?recursive=1")

        if tree.get("truncated"):
            logger.warning(
                "github_tree_truncated",
                repo=self._repo,
                detail="repository too large for one tree listing; some files were skipped",
            )

        for node in tree.get("tree", []):
            if node.get("type") != "blob":
                continue
            path = node["path"]
            source_type = _source_type(path)
            if source_type is None:
                continue
            if self._include and not any(path.startswith(p) for p in self._include):
                continue
            if node.get("size", 0) > self._max_bytes:
                logger.info("github_file_too_large", repo=self._repo, path=path)
                continue

            sha = node["sha"]
            yield SourceDocument(
                source_uri=f"github://{self._repo}/{path}",
                title=_title_from_path(path),
                source_type=source_type,
                access_groups=list(self._access_groups),
                loader=lambda sha=sha: self._blob(sha),  # type: ignore[misc]
                # git's own content hash: exact, and free to compare.
                revision=sha,
                department=self._department,
                doc_type=self._doc_type,
                classification=self._classification,
                source_updated_at=pushed_at,
                metadata={
                    "repo": self._repo,
                    "branch": branch,
                    "path": path,
                    "visibility": "private" if private else "public",
                    "html_url": f"https://github.com/{self._repo}/blob/{branch}/{path}",
                },
            )

    def _blob(self, sha: str) -> bytes:
        blob = self._get(f"/repos/{self._repo}/git/blobs/{sha}")
        if blob.get("encoding") != "base64":
            raise ConnectorError(f"{self._repo}: unexpected blob encoding {blob.get('encoding')}")
        return base64.b64decode(blob["content"])


def _source_type(path: str) -> str | None:
    for suffix, kind in _EXTENSIONS.items():
        if path.lower().endswith(suffix):
            return kind
    return None


def _title_from_path(path: str) -> str:
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    # A repo full of files called README is unreadable in a citation list, so
    # they carry the directory that gives them meaning.
    if stem.lower() == "readme" and "/" in path:
        return f"{path.rsplit('/', 2)[-2]} README"
    return stem.replace("-", " ").replace("_", " ").strip().title() or path


def _parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
