"""Jira Cloud REST v3 connector."""

from __future__ import annotations

import re
from typing import Any

import httpx

from ..models import JiraIssue
from ..text import adf_to_text

CUSTOMER_FIELD_RE = re.compile(
    r"customer|account|tenant|org(anization)?|client|severity|escalat|environment|case|region|"
    r"impact|edition|release|found in|root cause|steps to reproduce|expected|actual|workaround",
    re.I,
)
ANALYSIS_MARKER = "AI Engineering Quality & Impact Platform"


class JiraError(RuntimeError):
    pass


class JiraClient:
    def __init__(self, base_url: str, email: str | None, api_token: str | None,
                 transport: httpx.BaseTransport | None = None, timeout: float = 30.0):
        auth = (email, api_token) if email and api_token else None
        self.base_url = base_url.rstrip("/")
        self.http = httpx.Client(base_url=self.base_url, auth=auth, timeout=timeout, transport=transport,
                                 headers={"Accept": "application/json", "User-Agent": "aiqip/0.1"})

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self.http.request(method, path, **kwargs)
        if resp.status_code in (401, 403):
            raise JiraError(f"Jira {resp.status_code} for {path}: check JIRA_EMAIL / JIRA_API_TOKEN and project permissions.")
        if resp.status_code == 404:
            raise JiraError(f"Jira 404 for {path}: issue/resource does not exist or the account cannot see it.")
        if resp.status_code >= 400:
            raise JiraError(f"Jira {resp.status_code} for {method} {path}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    def browse_url(self, key: str) -> str:
        return f"{self.base_url}/browse/{key}"

    def get_issue(self, key: str) -> JiraIssue:
        data = self._request("GET", f"/rest/api/3/issue/{key}", params={"expand": "names,renderedFields"})
        comments = self._request("GET", f"/rest/api/3/issue/{key}/comment", params={"maxResults": 50})
        return issue_from_api(data, self.base_url, comments.get("comments", []))

    def search(self, jql: str, max_results: int = 500, fields: list[str] | None = None) -> list[dict[str, Any]]:
        fields = fields or ["summary", "description", "status", "priority", "components", "labels", "issuetype",
                            "created", "resolution", "fixVersions", "versions"]
        out: list[dict[str, Any]] = []
        token: str | None = None
        while len(out) < max_results:
            payload: dict[str, Any] = {"jql": jql, "maxResults": min(100, max_results - len(out)), "fields": fields}
            if token:
                payload["nextPageToken"] = token
            data = self._request("POST", "/rest/api/3/search/jql", json=payload)
            out.extend(data.get("issues", []))
            token = data.get("nextPageToken")
            if not token or data.get("isLast"):
                break
        return out

    def dashboard_jql(self, dashboard_id: str) -> list[str]:
        """Resolve the JQL behind each filter-backed gadget of a Jira dashboard."""
        gadgets = self._request("GET", f"/rest/api/3/dashboard/{dashboard_id}/gadget").get("gadgets", [])
        filter_ids: list[str] = []
        for g in gadgets:
            try:
                props = self._request("GET", f"/rest/api/3/dashboard/{dashboard_id}/items/{g['id']}/properties")
                for key in props.get("keys", []):
                    prop = self._request("GET", f"/rest/api/3/dashboard/{dashboard_id}/items/{g['id']}/properties/{key['key']}")
                    filter_ids.extend(_find_filter_ids(prop.get("value")))
            except JiraError:
                continue
        jqls: list[str] = []
        for fid in dict.fromkeys(filter_ids):
            try:
                jql = self._request("GET", f"/rest/api/3/filter/{fid}").get("jql")
                if jql and jql not in jqls:
                    jqls.append(jql)
            except JiraError:
                continue
        return jqls

    def linked_pull_requests(self, issue_id: str) -> list[dict[str, Any]]:
        """PRs linked through the GitHub for Jira dev panel (best effort; undocumented API)."""
        try:
            data = self._request("GET", "/rest/dev-status/latest/issue/detail",
                                 params={"issueId": issue_id, "applicationType": "GitHub", "dataType": "pullrequest"})
        except JiraError:
            return []
        prs: list[dict[str, Any]] = []
        for detail in data.get("detail", []):
            prs.extend(detail.get("pullRequests", []))
        return prs

    def has_analysis_comment(self, key: str) -> bool:
        comments = self._request("GET", f"/rest/api/3/issue/{key}/comment", params={"maxResults": 100})
        return any(ANALYSIS_MARKER in adf_to_text(c.get("body")) for c in comments.get("comments", []))

    def add_comment(self, key: str, adf_body: dict[str, Any]) -> str:
        data = self._request("POST", f"/rest/api/3/issue/{key}/comment", json={"body": adf_body})
        return f"{self.browse_url(key)}?focusedCommentId={data.get('id', '')}"


def _find_filter_ids(value: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if k.lower() in ("filterid", "filter_id") and v:
                ids.append(str(v).replace("filter-", ""))
            else:
                ids.extend(_find_filter_ids(v))
    elif isinstance(value, list):
        for v in value:
            ids.extend(_find_filter_ids(v))
    elif isinstance(value, str):
        m = re.fullmatch(r"filter-(\d+)", value)
        if m:
            ids.append(m.group(1))
    return ids


def _field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        if value.get("type") == "doc":
            return adf_to_text(value).strip()
        return str(value.get("value") or value.get("name") or value.get("displayName") or "")
    if isinstance(value, list):
        return ", ".join(t for t in (_field_text(v) for v in value) if t)
    return str(value)


def issue_from_api(data: dict[str, Any], base_url: str, comments: list[dict[str, Any]] | None = None) -> JiraIssue:
    f = data.get("fields", {})
    names = data.get("names", {})
    customer: dict[str, str] = {}
    for fid, value in f.items():
        if not fid.startswith("customfield_"):
            continue
        label = names.get(fid, fid)
        text = _field_text(value)
        if text and CUSTOMER_FIELD_RE.search(label):
            customer[label] = text[:1000]
    return JiraIssue(
        key=data["key"],
        summary=f.get("summary") or "",
        issue_type=(f.get("issuetype") or {}).get("name", ""),
        status=(f.get("status") or {}).get("name", ""),
        priority=(f.get("priority") or {}).get("name"),
        description=_field_text(f.get("description")),
        components=[c.get("name", "") for c in f.get("components") or []],
        labels=list(f.get("labels") or []),
        fix_versions=[v.get("name", "") for v in f.get("fixVersions") or []],
        affected_versions=[v.get("name", "") for v in f.get("versions") or []],
        reporter=(f.get("reporter") or {}).get("displayName"),
        assignee=(f.get("assignee") or {}).get("displayName"),
        created=f.get("created"),
        resolution=(f.get("resolution") or {}).get("name") if f.get("resolution") else None,
        customer_fields=customer,
        url=f"{base_url.rstrip('/')}/browse/{data['key']}",
        comments=[adf_to_text(c.get("body")).strip() for c in (comments or [])],
        issue_links=[
            {"type": (lnk.get("type") or {}).get("name", ""),
             "key": (lnk.get("outwardIssue") or lnk.get("inwardIssue") or {}).get("key", ""),
             "summary": ((lnk.get("outwardIssue") or lnk.get("inwardIssue") or {}).get("fields") or {}).get("summary", "")}
            for lnk in f.get("issuelinks") or []
        ],
    )
