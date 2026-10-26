"""GitHub REST connector (read PRs, code, commits; write comments, statuses, checks, dispatches)."""

from __future__ import annotations

import base64
import io
import time
import zipfile
from typing import Any

import httpx

from ..models import ChangedFile, PullRequest

COMMENT_MARKER = "<!-- aiqip:pr-quality-report -->"


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token: str | None, api_url: str = "https://api.github.com",
                 transport: httpx.BaseTransport | None = None, timeout: float = 30.0):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "aiqip/0.1"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.Client(base_url=api_url.rstrip("/"), headers=headers, timeout=timeout,
                                 transport=transport, follow_redirects=True)

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        resp = self.http.request(method, path, **kwargs)
        if resp.status_code == 404:
            raise GitHubError(f"GitHub 404 for {path}: repository or resource not found, or the token "
                              "has no access to it (private repos need a token with repo/contents scope "
                              "and SSO authorization for the org).")
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub {resp.status_code} for {method} {path}: {resp.text[:300]}")
        return resp

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params=params or None).json()

    def paginate(self, path: str, per_page: int = 100, max_pages: int = 30, **params: Any) -> list[Any]:
        out: list[Any] = []
        for page in range(1, max_pages + 1):
            data = self.get(path, per_page=per_page, page=page, **params)
            items = data if isinstance(data, list) else data.get("items", [])
            out.extend(items)
            if len(items) < per_page:
                break
        return out

    # ---- Read -----------------------------------------------------------------------------
    def get_pull_request(self, repo: str, number: int) -> PullRequest:
        pr = self.get(f"/repos/{repo}/pulls/{number}")
        files = self.paginate(f"/repos/{repo}/pulls/{number}/files", max_pages=30)
        commits = self.paginate(f"/repos/{repo}/pulls/{number}/commits", max_pages=5)
        return pull_request_from_api(repo, pr, files, commits)

    def get_pull_request_diff(self, repo: str, number: int) -> str:
        resp = self._request("GET", f"/repos/{repo}/pulls/{number}",
                             headers={"Accept": "application/vnd.github.v3.diff"})
        return resp.text

    def get_file(self, repo: str, path: str, ref: str | None = None) -> str | None:
        try:
            data = self.get(f"/repos/{repo}/contents/{path}", **({"ref": ref} if ref else {}))
        except GitHubError:
            return None
        if isinstance(data, dict) and data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return None

    def get_tree(self, repo: str, ref: str) -> list[dict[str, Any]]:
        data = self.get(f"/repos/{repo}/git/trees/{ref}", recursive="1")
        return [t for t in data.get("tree", []) if t.get("type") == "blob"]

    def search_code(self, repo: str, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        data = self.get("/search/code", q=f"{query} repo:{repo}", per_page=min(max_results, 100))
        return data.get("items", [])

    def file_authors(self, repo: str, path: str, limit: int = 30) -> list[str]:
        commits = self.get(f"/repos/{repo}/commits", path=path, per_page=limit)
        authors = []
        for c in commits:
            login = (c.get("author") or {}).get("login") or (c.get("commit", {}).get("author") or {}).get("name")
            if login:
                authors.append(login)
        return authors

    # ---- Write (callers must enforce dry-run) --------------------------------------------
    def upsert_pr_comment(self, repo: str, number: int, body: str, marker: str = COMMENT_MARKER) -> str:
        body = body if marker in body else f"{marker}\n{body}"
        for c in self.paginate(f"/repos/{repo}/issues/{number}/comments", max_pages=10):
            if marker in (c.get("body") or ""):
                resp = self._request("PATCH", f"/repos/{repo}/issues/comments/{c['id']}", json={"body": body})
                return resp.json().get("html_url", "")
        resp = self._request("POST", f"/repos/{repo}/issues/{number}/comments", json={"body": body})
        return resp.json().get("html_url", "")

    def create_commit_status(self, repo: str, sha: str, state: str, description: str, context: str,
                             target_url: str | None = None) -> None:
        payload = {"state": state, "description": description[:140], "context": context}
        if target_url:
            payload["target_url"] = target_url
        self._request("POST", f"/repos/{repo}/statuses/{sha}", json=payload)

    def create_check_run(self, repo: str, sha: str, name: str, conclusion: str, title: str, summary: str,
                         text: str | None = None, details_url: str | None = None) -> str:
        payload: dict[str, Any] = {"name": name, "head_sha": sha, "status": "completed", "conclusion": conclusion,
                                   "output": {"title": title[:255], "summary": summary[:65000]}}
        if text:
            payload["output"]["text"] = text[:65000]
        if details_url:
            payload["details_url"] = details_url
        return self._request("POST", f"/repos/{repo}/check-runs", json=payload).json().get("html_url", "")

    def dispatch_workflow(self, repo: str, workflow: str, ref: str, inputs: dict[str, str]) -> None:
        self._request("POST", f"/repos/{repo}/actions/workflows/{workflow}/dispatches",
                      json={"ref": ref, "inputs": inputs})

    def find_workflow_run(self, repo: str, workflow: str, correlation_id: str, created_after: str,
                          timeout_s: int = 300, poll_s: int = 10) -> dict[str, Any] | None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            runs = self.get(f"/repos/{repo}/actions/workflows/{workflow}/runs", event="workflow_dispatch",
                            created=f">={created_after}", per_page=30).get("workflow_runs", [])
            for run in runs:
                if correlation_id in (run.get("display_title") or "") or correlation_id in (run.get("name") or ""):
                    return run
            time.sleep(poll_s)
        return None

    def wait_for_run(self, repo: str, run_id: int, timeout_s: int, poll_s: int) -> dict[str, Any]:
        deadline = time.time() + timeout_s
        run: dict[str, Any] = {}
        while time.time() < deadline:
            run = self.get(f"/repos/{repo}/actions/runs/{run_id}")
            if run.get("status") == "completed":
                return run
            time.sleep(poll_s)
        return run

    def download_artifact_files(self, repo: str, run_id: int, artifact_name: str) -> dict[str, bytes]:
        arts = self.get(f"/repos/{repo}/actions/runs/{run_id}/artifacts").get("artifacts", [])
        art = next((a for a in arts if a.get("name") == artifact_name), None)
        if not art:
            return {}
        resp = self._request("GET", f"/repos/{repo}/actions/artifacts/{art['id']}/zip")
        out: dict[str, bytes] = {}
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for name in zf.namelist():
                if not name.endswith("/"):
                    out[name] = zf.read(name)
        return out


def pull_request_from_api(repo: str, pr: dict[str, Any], files: list[dict[str, Any]],
                          commits: list[dict[str, Any]]) -> PullRequest:
    return PullRequest(
        repo=repo,
        number=pr["number"],
        title=pr.get("title") or "",
        body=pr.get("body") or "",
        author=(pr.get("user") or {}).get("login", ""),
        head_sha=(pr.get("head") or {}).get("sha", ""),
        base_ref=(pr.get("base") or {}).get("ref", ""),
        head_ref=(pr.get("head") or {}).get("ref", ""),
        url=pr.get("html_url", ""),
        labels=[lbl.get("name", "") for lbl in pr.get("labels", [])],
        commits=[(c.get("commit") or {}).get("message", "") for c in commits],
        files=[
            ChangedFile(
                path=f["filename"],
                status=f.get("status", "modified"),
                additions=f.get("additions", 0),
                deletions=f.get("deletions", 0),
                patch=f.get("patch"),
                previous_path=f.get("previous_filename"),
            )
            for f in files
        ],
    )
