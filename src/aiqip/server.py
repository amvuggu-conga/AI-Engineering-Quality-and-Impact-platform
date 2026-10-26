"""Webhook server (stdlib only).

* ``POST /webhooks/github`` - GitHub ``pull_request`` events (opened, synchronize, reopened,
  ready_for_review). Verified with ``X-Hub-Signature-256`` and ``AIQ_GITHUB_WEBHOOK_SECRET``.
* ``POST /webhooks/jira`` - Jira Automation "Send web request" / Jira webhook with the issue
  payload. Verified with header ``X-AIQ-Token`` equal to ``AIQ_JIRA_WEBHOOK_SECRET``.
* ``GET /healthz``

Posting still requires ``AIQ_POST=true``; test execution requires ``AIQ_EXECUTE=true``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from .config import Settings, _env_bool
from .connectors.github import GitHubClient
from .connectors.jira import JiraClient
from .feedback import publish_bug_report, publish_pr_report
from .llm import build_llm
from .workflows.customer_bug import run_bug_analysis
from .workflows.pr_quality import run_pr_quality

log = logging.getLogger(__name__)
PR_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


def verify_github_signature(secret: str | None, body: bytes, signature: str | None) -> bool:
    if not secret:
        return False
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def handle_github_event(event: str, payload: dict[str, Any]) -> tuple[str, str, int] | None:
    if event != "pull_request" or payload.get("action") not in PR_ACTIONS:
        return None
    pr = payload.get("pull_request") or {}
    if pr.get("draft"):
        return None
    return payload["repository"]["full_name"], "pr", int(pr["number"])


def handle_jira_event(payload: dict[str, Any], issue_types: set[str]) -> str | None:
    issue = payload.get("issue") or {}
    key = issue.get("key") or payload.get("issueKey")
    itype = ((issue.get("fields") or {}).get("issuetype") or {}).get("name")
    if not key:
        return None
    if itype and issue_types and itype.lower() not in issue_types:
        return None
    return key


def make_handler(settings: Settings, runner: Callable[[str, Any], None]) -> type[BaseHTTPRequestHandler]:
    gh_secret = os.environ.get("AIQ_GITHUB_WEBHOOK_SECRET")
    jira_secret = os.environ.get("AIQ_JIRA_WEBHOOK_SECRET")
    issue_types = {t.strip().lower() for t in os.environ.get("AIQ_JIRA_ISSUE_TYPES", "Bug").split(",") if t.strip()}

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, code: int, msg: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"message": msg}).encode())

        def log_message(self, fmt: str, *args: Any) -> None:  # route through logging
            log.info(fmt, *args)

        def do_GET(self) -> None:
            self._reply(200 if self.path == "/healthz" else 404, "ok" if self.path == "/healthz" else "not found")

        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
            try:
                payload = json.loads(body or b"{}")
            except json.JSONDecodeError:
                return self._reply(400, "invalid json")
            if self.path.startswith("/webhooks/github"):
                if not verify_github_signature(gh_secret, body, self.headers.get("X-Hub-Signature-256")):
                    return self._reply(401, "bad signature")
                job = handle_github_event(self.headers.get("X-GitHub-Event", ""), payload)
                if not job:
                    return self._reply(202, "ignored")
                runner("pr", job)
                return self._reply(202, f"queued PR quality for {job[0]}#{job[2]}")
            if self.path.startswith("/webhooks/jira"):
                token = self.headers.get("X-AIQ-Token", "")
                if not jira_secret or not hmac.compare_digest(token, jira_secret):
                    return self._reply(401, "bad token")
                key = handle_jira_event(payload, issue_types)
                if not key:
                    return self._reply(202, "ignored")
                runner("bug", key)
                return self._reply(202, f"queued bug analysis for {key}")
            return self._reply(404, "not found")

    return Handler


def _default_runner(settings: Settings) -> Callable[[str, Any], None]:
    execute = _env_bool("AIQ_EXECUTE")

    def run(kind: str, job: Any) -> None:
        def work() -> None:
            try:
                github = GitHubClient(settings.github_token, settings.github_api_url)
                jira = JiraClient(settings.jira_base_url, settings.jira_email, settings.jira_api_token) \
                    if settings.jira_configured else None
                llm = build_llm(settings)
                if kind == "pr":
                    repo, _, number = job
                    report = run_pr_quality(settings, github, jira, llm, repo, number, execute=execute)
                    res = publish_pr_report(settings, github, report)
                    log.info("PR %s#%s -> %s (posted=%s)", repo, number, report.gate.decision.value, res["posted"])
                elif jira is not None:
                    report = run_bug_analysis(settings, jira, github, llm, job)
                    res = publish_bug_report(settings, jira, report)
                    log.info("Bug %s analysed (posted=%s)", job, res["posted"])
            except Exception:
                log.exception("Job %s %s failed", kind, job)

        threading.Thread(target=work, daemon=True).start()

    return run


def serve(settings: Settings, host: str = "0.0.0.0", port: int = 8080) -> int:
    logging.basicConfig(level=logging.INFO)
    server = ThreadingHTTPServer((host, port), make_handler(settings, _default_runner(settings)))
    log.info("aiqip webhook server on %s:%s (post=%s)", host, port, settings.post)
    server.serve_forever()
    return 0
