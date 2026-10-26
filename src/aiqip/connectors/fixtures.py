"""Offline fixture sources that mirror the GitHub/Jira connectors.

Layout (produced by ``aiqip snapshot``; raw API payloads, nothing transformed)::

    <dir>/github/<owner>__<repo>/pulls/<n>.json          GET /repos/{repo}/pulls/{n}
    <dir>/github/<owner>__<repo>/pulls/<n>.files.json    GET /repos/{repo}/pulls/{n}/files
    <dir>/github/<owner>__<repo>/pulls/<n>.commits.json  GET /repos/{repo}/pulls/{n}/commits
    <dir>/github/<owner>__<repo>/authors.json            {"path": ["login", ...]} (optional)
    <dir>/jira/issues/<KEY>.json                         GET /rest/api/3/issue/{key}?expand=names
    <dir>/jira/issues/<KEY>.comments.json                GET /rest/api/3/issue/{key}/comment
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import JiraIssue, PullRequest
from .github import GitHubError, pull_request_from_api
from .jira import JiraError, issue_from_api


def _repo_dir(repo: str) -> str:
    return repo.replace("/", "__")


def _load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


class FixtureGitHub:
    def __init__(self, root: str | Path):
        self.root = Path(root) / "github"

    def get_pull_request(self, repo: str, number: int) -> PullRequest:
        base = self.root / _repo_dir(repo) / "pulls"
        pr = _load(base / f"{number}.json")
        if pr is None:
            raise GitHubError(f"No fixture for {repo}#{number} under {base}")
        return pull_request_from_api(repo, pr, _load(base / f"{number}.files.json", []),
                                     _load(base / f"{number}.commits.json", []))

    def file_authors(self, repo: str, path: str, limit: int = 30) -> list[str]:
        return (_load(self.root / _repo_dir(repo) / "authors.json", {}) or {}).get(path, [])[:limit]

    def get_file(self, repo: str, path: str, ref: str | None = None) -> str | None:
        return None

    def search_code(self, repo: str, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        return []

    def __getattr__(self, name: str) -> Any:
        if name.startswith(("upsert_", "create_", "dispatch_")):
            def _blocked(*_: Any, **__: Any) -> Any:
                raise GitHubError("Fixture mode is read-only; posting is not possible.")
            return _blocked
        raise AttributeError(name)


class FixtureJira:
    def __init__(self, root: str | Path, base_url: str = "https://conga.atlassian.net"):
        self.root = Path(root) / "jira"
        self.base_url = base_url.rstrip("/")

    def browse_url(self, key: str) -> str:
        return f"{self.base_url}/browse/{key}"

    def get_issue(self, key: str) -> JiraIssue:
        data = _load(self.root / "issues" / f"{key}.json")
        if data is None:
            raise JiraError(f"No fixture for Jira issue {key} under {self.root / 'issues'}")
        comments = _load(self.root / "issues" / f"{key}.comments.json", {}) or {}
        return issue_from_api(data, self.base_url, comments.get("comments", []))

    def search(self, jql: str, max_results: int = 500, fields: list[str] | None = None) -> list[dict[str, Any]]:
        return (_load(self.root / "search.json", {}) or {}).get("issues", [])[:max_results]

    def dashboard_jql(self, dashboard_id: str) -> list[str]:
        return []

    def linked_pull_requests(self, issue_id: str) -> list[dict[str, Any]]:
        return []

    def has_analysis_comment(self, key: str) -> bool:
        return False

    def add_comment(self, key: str, adf_body: dict[str, Any]) -> str:
        raise JiraError("Fixture mode is read-only; posting is not possible.")
