"""Automated feedback loops back to GitHub (PR comment + quality gate) and Jira (analysis comment).

These are the only functions that write to external systems. They do nothing but return the
rendered payloads unless ``settings.post`` is true (``--post`` / ``AIQ_POST=true``).
"""

from __future__ import annotations

import logging
from typing import Any

from .config import Settings
from .reporting.adf import adf_to_markdown
from .reporting.jira_report import render_jira_comment
from .reporting.pr_report import gate_conclusion, gate_status, render_pr_comment
from .workflows.customer_bug import BugAnalysisReport
from .workflows.pr_quality import PRQualityReport

log = logging.getLogger(__name__)


def publish_pr_report(settings: Settings, github: Any, report: PRQualityReport,
                      details_url: str | None = None) -> dict[str, Any]:
    pr = report.understanding.pr
    comment = render_pr_comment(report)
    state, description = gate_status(report, settings.gate.review_state)
    result: dict[str, Any] = {"posted": False, "comment": comment, "status": {"state": state, "description": description,
                                                                              "context": settings.gate.status_context}}
    if not settings.post:
        return result
    result["comment_url"] = github.upsert_pr_comment(pr.repo, pr.number, comment)
    if settings.gate.report_mode == "check":
        result["check_url"] = github.create_check_run(pr.repo, pr.head_sha, settings.gate.status_context,
                                                      gate_conclusion(report), description, comment[:65000],
                                                      details_url=details_url)
    else:
        github.create_commit_status(pr.repo, pr.head_sha, state, description, settings.gate.status_context,
                                    details_url or result.get("comment_url"))
    result["posted"] = True
    return result


def publish_bug_report(settings: Settings, jira: Any, report: BugAnalysisReport, force: bool = False) -> dict[str, Any]:
    adf = render_jira_comment(report)
    result: dict[str, Any] = {"posted": False, "adf": adf, "markdown": adf_to_markdown(adf)}
    if not settings.post:
        return result
    key = report.bug.issue.key
    if not force and jira.has_analysis_comment(key):
        result["skipped"] = "An AI analysis comment already exists on this issue (use --force to add another)."
        return result
    result["comment_url"] = jira.add_comment(key, adf)
    result["posted"] = True
    return result
