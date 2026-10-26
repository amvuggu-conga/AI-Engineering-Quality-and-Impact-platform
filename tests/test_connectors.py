import json

import httpx
import pytest

from aiqip.connectors.docs import DocsClient, extract_article_text, page_from_url
from aiqip.connectors.github import COMMENT_MARKER, GitHubClient, GitHubError
from aiqip.connectors.jira import JiraClient


def test_github_reads_pr_with_pagination_and_auth_header():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/repos/o/r/pulls/7":
            return httpx.Response(200, json={"number": 7, "title": "T", "body": "Fixes CONTRACTS-1", "user": {"login": "u"},
                                             "head": {"sha": "abc", "ref": "h"}, "base": {"ref": "master"},
                                             "html_url": "https://github.com/o/r/pull/7", "labels": []})
        if path == "/repos/o/r/pulls/7/files":
            page = int(request.url.params["page"])
            n = 100 if page == 1 else 3
            return httpx.Response(200, json=[{"filename": f"f{page}_{i}.cs", "status": "modified", "additions": 1,
                                              "deletions": 0, "patch": "@@ -1 +1 @@\n+x"} for i in range(n)])
        if path == "/repos/o/r/pulls/7/commits":
            return httpx.Response(200, json=[{"commit": {"message": "CONTRACTS-1 change"}}])
        return httpx.Response(404)

    gh = GitHubClient("tok", transport=httpx.MockTransport(handler))
    pr = gh.get_pull_request("o/r", 7)
    assert len(pr.files) == 103 and pr.head_sha == "abc" and pr.commits == ["CONTRACTS-1 change"]
    assert seen[0].headers["Authorization"] == "Bearer tok"


def test_github_404_explains_access():
    gh = GitHubClient(None, transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(GitHubError, match="no access"):
        gh.get_pull_request("congaengr/ROC-CLM-API", 2248)


def test_github_upsert_comment_updates_existing_marker_comment():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": 5, "body": "other"}, {"id": 9, "body": f"{COMMENT_MARKER}\nold"}])
        return httpx.Response(200, json={"html_url": "https://x/9"})

    gh = GitHubClient("t", transport=httpx.MockTransport(handler))
    assert gh.upsert_pr_comment("o/r", 1, "new body") == "https://x/9"
    assert ("PATCH", "/repos/o/r/issues/comments/9") in calls


def test_jira_get_issue_maps_customer_fields_and_comments():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comment"):
            return httpx.Response(200, json={"comments": [{"body": {"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "seen at Acme"}]}]}}]})
        return httpx.Response(200, json={
            "key": "CONTRACTS-9", "names": {"customfield_1": "Customer Name", "customfield_2": "Story Points"},
            "fields": {"summary": "S", "issuetype": {"name": "Bug"}, "status": {"name": "Open"},
                       "priority": {"name": "P1"}, "description": "plain", "customfield_1": {"value": "Acme"},
                       "customfield_2": 3}})

    jira = JiraClient("https://conga.atlassian.net", "e", "t", transport=httpx.MockTransport(handler))
    issue = jira.get_issue("CONTRACTS-9")
    assert issue.customer_fields == {"Customer Name": "Acme"}
    assert issue.comments == ["seen at Acme"]
    assert issue.url == "https://conga.atlassian.net/browse/CONTRACTS-9"


def test_jira_search_uses_next_page_token():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "nextPageToken" not in body:
            return httpx.Response(200, json={"issues": [{"key": "A-1"}], "nextPageToken": "p2"})
        return httpx.Response(200, json={"issues": [{"key": "A-2"}], "isLast": True})

    jira = JiraClient("https://j", "e", "t", transport=httpx.MockTransport(handler))
    assert [i["key"] for i in jira.search("project = A")] == ["A-1", "A-2"]
    assert bodies[1]["nextPageToken"] == "p2"


def test_jira_dashboard_jql_resolves_filters():
    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p.endswith("/gadget"):
            return httpx.Response(200, json={"gadgets": [{"id": 11}]})
        if p.endswith("/items/11/properties"):
            return httpx.Response(200, json={"keys": [{"key": "config"}]})
        if p.endswith("/items/11/properties/config"):
            return httpx.Response(200, json={"value": {"filterId": "filter-4242"}})
        if p.endswith("/filter/4242"):
            return httpx.Response(200, json={"jql": "labels = escape_defect"})
        return httpx.Response(404)

    jira = JiraClient("https://j", "e", "t", transport=httpx.MockTransport(handler))
    assert jira.dashboard_jql("36628") == ["labels = escape_defect"]


ARTICLE = "<html><title>Renewing an Agreement | Conga</title><nav>menu</nav><article id='t'><h1>Renew</h1><p>Use Renew to extend the term.</p></article></html>"


def test_docs_extract_and_slug_title():
    title, text = extract_article_text(ARTICLE)
    assert title == "Renewing an Agreement" and "extend the term" in text and "menu" not in text
    page = page_from_url("https://documentation.conga.com/en/clm-for-advantage-platform/current/clm-for-users/contract-details-and-actions/renewing-an-agreement")
    assert page["title"] == "Renewing an Agreement" and page["section"] == "CLM for Users > Contract Details and Actions"


def test_docs_crawl_sitemap_index_and_retries_shell_page(monkeypatch):
    monkeypatch.setattr("aiqip.connectors.docs.time.sleep", lambda s: None)
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/sitemap.xml") and "clm" not in url:
            return httpx.Response(200, text="<sitemapindex><sitemap><loc>https://d/en/clm/sitemap.xml</loc></sitemap></sitemapindex>")
        if url.endswith("/clm/sitemap.xml"):
            return httpx.Response(200, text="<urlset><url><loc>https://d/en/clm/current/renewing-an-agreement</loc></url></urlset>")
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(200, text="<html>You seem to be using an unsupported browser</html>")
        return httpx.Response(200, text=ARTICLE)

    pages = DocsClient(transport=httpx.MockTransport(handler)).crawl(["https://d/sitemap.xml"], fetch_content=True, delay_s=0)
    assert len(pages) == 1 and "extend the term" in pages[0]["text"] and "error" not in pages[0]
    assert hits["n"] == 2
