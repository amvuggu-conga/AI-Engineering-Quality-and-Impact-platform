"""Command-line interface: ``aiqip <command>``. Dry-run is the default for every command."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from .config import RepoConfig, Settings, load_settings
from .connectors.docs import DocsClient
from .connectors.fixtures import FixtureGitHub, FixtureJira
from .connectors.github import GitHubClient
from .connectors.jira import JiraClient
from .feedback import publish_bug_report, publish_pr_report
from .intelligence.code_index import build_code_index
from .intelligence.defects import build_defect_index
from .intelligence.knowledge import build_docs_index
from .intelligence.layer import index_file
from .intelligence.test_index import build_test_index
from .llm import build_llm
from .repos import ensure_clone
from .workflows.customer_bug import run_bug_analysis
from .workflows.pr_quality import run_pr_quality

log = logging.getLogger("aiqip")


def make_github(settings: Settings, fixtures: str | None) -> Any:
    return FixtureGitHub(fixtures) if fixtures else GitHubClient(settings.github_token, settings.github_api_url)


def make_jira(settings: Settings, fixtures: str | None) -> Any | None:
    if fixtures:
        return FixtureJira(fixtures, settings.jira_base_url)
    if settings.jira_configured:
        return JiraClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token)
    return None


def _write(path: str | Path, content: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _banner(settings: Settings, what: str) -> None:
    mode = "POST MODE - results WILL be written" if settings.post else "DRY RUN - nothing will be posted"
    print(f"== {what} :: {mode} ==", file=sys.stderr)


def cmd_pr_quality(args: argparse.Namespace, settings: Settings) -> int:
    if args.post:
        settings.post = True
    if args.fixtures and settings.post:
        print("Refusing to post in fixture mode.", file=sys.stderr)
        return 2
    _banner(settings, f"PR Quality Intelligence {args.repo}#{args.pr}")
    github = make_github(settings, args.fixtures)
    jira = make_jira(settings, args.fixtures)
    report = run_pr_quality(settings, github, jira, build_llm(settings), args.repo, args.pr, execute=args.execute)
    published = publish_pr_report(settings, github, report, details_url=args.details_url)
    if args.out:
        _write(Path(args.out) / "pr-quality-report.md", published["comment"])
        _write(Path(args.out) / "pr-quality-report.json", json.dumps(report.to_json(), indent=2, default=str))
    print(published["comment"])
    print(f"\n[quality gate] {published['status']['context']}: {published['status']['state']} - "
          f"{published['status']['description']}", file=sys.stderr)
    if published["posted"]:
        print(f"[posted] {published.get('comment_url', '')}", file=sys.stderr)
    if args.fail_on_block and report.gate.decision.value == "BLOCK":
        return 1
    return 0


def cmd_bug_analysis(args: argparse.Namespace, settings: Settings) -> int:
    if args.post:
        settings.post = True
    if args.fixtures and settings.post:
        print("Refusing to post in fixture mode.", file=sys.stderr)
        return 2
    _banner(settings, f"Customer bug analysis {args.issue}")
    jira = make_jira(settings, args.fixtures)
    if jira is None:
        print("Jira is not configured: set JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN (or use --fixtures).",
              file=sys.stderr)
        return 2
    github = make_github(settings, args.fixtures) if (args.fixtures or settings.github_token) else None
    report = run_bug_analysis(settings, jira, github, build_llm(settings), args.issue)
    published = publish_bug_report(settings, jira, report, force=args.force)
    if args.out:
        _write(Path(args.out) / "jira-analysis.md", published["markdown"])
        _write(Path(args.out) / "jira-analysis.adf.json", json.dumps(published["adf"], indent=2))
        _write(Path(args.out) / "jira-analysis.json", json.dumps(report.to_json(), indent=2, default=str))
    print(published["markdown"])
    if published.get("skipped"):
        print(f"[skipped] {published['skipped']}", file=sys.stderr)
    if published["posted"]:
        print(f"[posted] {published.get('comment_url', '')}", file=sys.stderr)
    return 0


def _repo_cfg(settings: Settings, name: str | None, default: RepoConfig) -> RepoConfig:
    if not name:
        return default
    for r in settings.dev_repos + [settings.automation_repo]:
        if r.name == name:
            return r
    return RepoConfig(name, default.branch, default.kind)


def _resolve_path(args: argparse.Namespace, settings: Settings, repo: RepoConfig) -> Path:
    if args.path:
        return Path(args.path)
    if repo.local_path:
        return Path(repo.local_path)
    return ensure_clone(repo.name, args.branch or repo.branch, Path(settings.index_dir).parent / "repos",
                        settings.github_token)


def cmd_index(args: argparse.Namespace, settings: Settings) -> int:
    out_dir = Path(settings.index_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.target == "code":
        repos = [_repo_cfg(settings, args.repo, settings.dev_repos[0])] if args.repo else settings.dev_repos
        for repo in repos:
            root = _resolve_path(args, settings, repo)
            data = build_code_index(repo.name, root, args.kind or repo.kind, with_git=not args.no_git)
            path = index_file(out_dir, "code", repo.name)
            path.write_text(json.dumps(data))
            eps = sum(len(f["endpoints"]) for f in data["files"].values())
            print(f"Indexed {repo.name}: {len(data['files'])} files, {eps} API endpoints, "
                  f"{len(data['ownership'])} files with ownership -> {path}")
    elif args.target == "tests":
        repo = _repo_cfg(settings, args.repo, settings.automation_repo)
        root = _resolve_path(args, settings, repo)
        data = build_test_index(repo.name, root, args.mapping)
        path = index_file(out_dir, "tests", repo.name)
        path.write_text(json.dumps(data))
        print(f"Indexed {repo.name}: {len(data['tests'])} tests, frameworks {data['frameworks']} -> {path}")
    elif args.target == "docs":
        client = DocsClient()
        sitemaps = args.sitemap or settings.docs.sitemaps
        pages = client.crawl(sitemaps, fetch_content=args.fetch_content or settings.docs.fetch_content,
                             max_pages=args.max_pages or settings.docs.max_pages)
        data = build_docs_index(pages, ", ".join(sitemaps))
        path = Path(args.out) if args.out else index_file(out_dir, "docs")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, separators=(",", ":")))
        print(f"Indexed {len(pages)} documentation pages -> {path}")
    elif args.target == "defects":
        jira = make_jira(settings, args.fixtures)
        if jira is None:
            print("Jira is not configured (JIRA_EMAIL / JIRA_API_TOKEN).", file=sys.stderr)
            return 2
        jqls = list(args.jql or []) + list(settings.defects.extra_jql)
        dashboard = args.dashboard or settings.defects.dashboard_id
        if dashboard and not args.jql:
            found = jira.dashboard_jql(dashboard)
            print(f"Dashboard {dashboard}: {len(found)} filter JQL(s) resolved", file=sys.stderr)
            jqls.extend(found)
        if not jqls:
            print("No JQL resolved; pass --jql (e.g. 'issuetype = Bug AND labels = escape_defect').", file=sys.stderr)
            return 2
        issues: dict[str, Any] = {}
        for jql in jqls:
            for issue in jira.search(jql, max_results=settings.defects.max_results):
                issues[issue["key"]] = issue
        data = build_defect_index(list(issues.values()), settings.jira_base_url, jqls)
        path = index_file(out_dir, "defects")
        path.write_text(json.dumps(data))
        print(f"Indexed {len(issues)} historical defects -> {path}")
    return 0


def cmd_snapshot(args: argparse.Namespace, settings: Settings) -> int:
    """Record raw API payloads as fixtures for offline replay (no transformation)."""
    out = Path(args.out)
    if args.kind == "pr":
        gh = GitHubClient(settings.github_token, settings.github_api_url)
        base = out / "github" / args.repo.replace("/", "__") / "pulls"
        base.mkdir(parents=True, exist_ok=True)
        (base / f"{args.pr}.json").write_text(json.dumps(gh.get(f"/repos/{args.repo}/pulls/{args.pr}"), indent=1))
        (base / f"{args.pr}.files.json").write_text(json.dumps(gh.paginate(f"/repos/{args.repo}/pulls/{args.pr}/files"), indent=1))
        (base / f"{args.pr}.commits.json").write_text(json.dumps(gh.paginate(f"/repos/{args.repo}/pulls/{args.pr}/commits"), indent=1))
        print(f"Saved PR fixtures under {base}")
    else:
        if not settings.jira_configured:
            print("Jira is not configured.", file=sys.stderr)
            return 2
        jira = JiraClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token)
        base = out / "jira" / "issues"
        base.mkdir(parents=True, exist_ok=True)
        data = jira._request("GET", f"/rest/api/3/issue/{args.issue}", params={"expand": "names"})
        comments = jira._request("GET", f"/rest/api/3/issue/{args.issue}/comment", params={"maxResults": 50})
        (base / f"{args.issue}.json").write_text(json.dumps(data, indent=1))
        (base / f"{args.issue}.comments.json").write_text(json.dumps(comments, indent=1))
        print(f"Saved Jira fixtures under {base}")
    return 0


def cmd_doctor(args: argparse.Namespace, settings: Settings) -> int:
    print(json.dumps(settings.redacted(), indent=2))
    checks: list[tuple[str, str]] = []
    gh = GitHubClient(settings.github_token, settings.github_api_url)
    for repo in [r.name for r in settings.dev_repos] + [settings.automation_repo.name]:
        try:
            info = gh.get(f"/repos/{repo}")
            checks.append((f"GitHub {repo}", f"OK (default branch {info.get('default_branch')})"))
        except Exception as exc:
            checks.append((f"GitHub {repo}", f"FAIL - {str(exc)[:160]}"))
    jira = make_jira(settings, None)
    if jira is None:
        checks.append(("Jira", "NOT CONFIGURED (JIRA_EMAIL / JIRA_API_TOKEN)"))
    else:
        try:
            me = jira._request("GET", "/rest/api/3/myself")
            checks.append(("Jira", f"OK ({me.get('displayName')})"))
        except Exception as exc:
            checks.append(("Jira", f"FAIL - {str(exc)[:160]}"))
    llm = build_llm(settings)
    checks.append(("LLM", f"{llm.name} ({'available' if llm.available else 'not configured - deterministic mode'})"))
    from .intelligence.layer import IntelligenceLayer
    layer = IntelligenceLayer.load(settings.index_dir, [r.name for r in settings.dev_repos],
                                   settings.automation_repo.name, settings.knowledge_file)
    for k, v in layer.status().items():
        checks.append((f"Index: {k}", v))
    width = max(len(k) for k, _ in checks)
    for k, v in checks:
        print(f"{k.ljust(width)}  {v}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aiqip", description="AI Engineering Quality & Impact Platform")
    p.add_argument("--config", help="Path to aiqip.yaml (default: ./aiqip.yaml or $AIQ_CONFIG)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    pr = sub.add_parser("pr-quality", help="Use case 1: autonomous PR quality gate")
    pr.add_argument("--repo", required=True, help="owner/name, e.g. congaengr/ROC-CLM-API")
    pr.add_argument("--pr", required=True, type=int)
    pr.add_argument("--post", action="store_true", help="Post the PR comment and commit status (default: dry run)")
    pr.add_argument("--execute", action="store_true", help="Trigger the configured test executor")
    pr.add_argument("--fixtures", help="Read GitHub/Jira from a fixture directory instead of the APIs")
    pr.add_argument("--out", help="Directory for pr-quality-report.md/.json")
    pr.add_argument("--details-url", help="Link for the status/check (e.g. the Actions run URL)")
    pr.add_argument("--fail-on-block", action="store_true", help="Exit 1 when the decision is BLOCK")
    pr.set_defaults(func=cmd_pr_quality)

    bug = sub.add_parser("bug-analysis", help="Use case 2: customer-aware Jira bug analysis")
    bug.add_argument("--issue", required=True, help="Jira key, e.g. CONTRACTS-12345")
    bug.add_argument("--post", action="store_true", help="Post the analysis comment to Jira (default: dry run)")
    bug.add_argument("--force", action="store_true", help="Post even if an AI analysis comment already exists")
    bug.add_argument("--fixtures", help="Read Jira from a fixture directory")
    bug.add_argument("--out", help="Directory for jira-analysis.md/.json")
    bug.set_defaults(func=cmd_bug_analysis)

    idx = sub.add_parser("index", help="Build the shared intelligence layer indexes")
    idx.add_argument("target", choices=["code", "tests", "docs", "defects"])
    idx.add_argument("--repo", help="owner/name (default: configured repos)")
    idx.add_argument("--path", help="Local checkout to index (otherwise a blobless clone is made)")
    idx.add_argument("--branch")
    idx.add_argument("--kind", choices=["api", "ui"])
    idx.add_argument("--no-git", action="store_true", help="Skip git ownership extraction")
    idx.add_argument("--mapping", help="Test mapping YAML (tests)")
    idx.add_argument("--sitemap", action="append", help="Docs sitemap URL (repeatable)")
    idx.add_argument("--fetch-content", action="store_true", help="Fetch page bodies, not just sitemap titles")
    idx.add_argument("--max-pages", type=int)
    idx.add_argument("--out", help="Output file (docs)")
    idx.add_argument("--dashboard", help="Jira dashboard id (defects)")
    idx.add_argument("--jql", action="append", help="JQL for historical defects (repeatable)")
    idx.add_argument("--fixtures")
    idx.set_defaults(func=cmd_index)

    snap = sub.add_parser("snapshot", help="Record live GitHub/Jira payloads as fixtures")
    snap.add_argument("kind", choices=["pr", "jira"])
    snap.add_argument("--repo")
    snap.add_argument("--pr", type=int)
    snap.add_argument("--issue")
    snap.add_argument("--out", required=True)
    snap.set_defaults(func=cmd_snapshot)

    doc = sub.add_parser("doctor", help="Show configuration and connectivity")
    doc.set_defaults(func=cmd_doctor)

    srv = sub.add_parser("serve", help="Run the GitHub/Jira webhook server")
    srv.add_argument("--host", default="0.0.0.0")
    srv.add_argument("--port", type=int, default=8080)
    srv.set_defaults(func=lambda a, s: __import__("aiqip.server", fromlist=["serve"]).serve(s, a.host, a.port))
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = load_settings(args.config)
    try:
        return args.func(args, settings) or 0
    except Exception as exc:
        if args.verbose:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
