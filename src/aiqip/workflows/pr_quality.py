"""Use case 1 - Autonomous PR Quality Intelligence (Development Track)."""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from .. import __version__
from ..analysis.impact import analyze_pr_impact
from ..analysis.pr_understanding import PRUnderstanding, understand_pr
from ..analysis.test_selection import find_test_gaps, select_tests
from ..config import Settings
from ..decision import decide
from ..execution.executors import run_tests
from ..execution.failure_analysis import analyze_failures
from ..intelligence.layer import IntelligenceLayer
from ..llm import LLMProvider
from ..models import ExecutionSummary, GateResult, ImpactReport, JiraIssue, SelectedTest, TestGap
from ..taxonomy import area_name
from ..text import tokenize, truncate

log = logging.getLogger(__name__)


@dataclass
class RequirementTrace:
    key: str
    found: bool
    summary: str = ""
    issue_type: str = ""
    status: str = ""
    url: str = ""
    alignment: str = "unknown"  # aligned | partial | unclear | misaligned | unknown
    notes: str = ""
    matched_terms: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class PRQualityReport:
    understanding: PRUnderstanding
    requirements: list[RequirementTrace]
    impact: ImpactReport
    selected: list[SelectedTest]
    gaps: list[TestGap]
    execution: ExecutionSummary
    gate: GateResult
    change_summary: str
    ai_used: bool
    ai_notes: list[str]
    layer_status: dict[str, str]
    generated_at: str
    framework: str
    dry_run: bool = True
    version: str = __version__

    def to_json(self) -> dict[str, Any]:
        from ..models import to_dict
        pu = self.understanding
        return {
            "version": self.version, "generated_at": self.generated_at, "dry_run": self.dry_run,
            "pr": {"repo": pu.pr.repo, "number": pu.pr.number, "title": pu.pr.title, "url": pu.pr.url,
                   "head_sha": pu.pr.head_sha, "author": pu.pr.author, **pu.stats},
            "decision": self.gate.decision.value, "reasons": self.gate.reasons, "evidence": self.gate.evidence,
            "change_summary": self.change_summary, "requirements": to_dict(self.requirements),
            "impact": to_dict(self.impact), "changed_members": to_dict(pu.members),
            "selected_tests": [{"id": s.test.id, "score": s.score, "reasons": s.reasons, "areas": s.test.areas}
                               for s in self.selected],
            "test_gaps": to_dict(self.gaps), "execution": to_dict(self.execution),
            "intelligence_layer": self.layer_status, "ai_used": self.ai_used, "ai_notes": self.ai_notes,
        }


def _trace_requirement(key: str, jira: Any, pu: PRUnderstanding) -> tuple[RequirementTrace, JiraIssue | None]:
    try:
        issue = jira.get_issue(key)
    except Exception as exc:
        return RequirementTrace(key=key, found=False, url=jira.browse_url(key) if jira else "", error=str(exc)), None
    req_terms = set(tokenize(f"{issue.summary} {issue.description}"))
    matched = sorted(req_terms & set(pu.terms))
    ratio = len(matched) / max(1, min(len(req_terms), 25))
    alignment = "aligned" if ratio >= 0.4 else "partial" if ratio >= 0.15 else "unclear"
    return RequirementTrace(key=key, found=True, summary=issue.summary, issue_type=issue.issue_type, status=issue.status,
                            url=issue.url or "", alignment=alignment, matched_terms=matched[:12],
                            notes=f"{len(matched)} requirement terms found in the change (heuristic)."), issue


def _heuristic_summary(pu: PRUnderstanding, impact: ImpactReport) -> str:
    cats = ", ".join(f"{len(v)} {k}" for k, v in sorted(pu.files_by_category.items(), key=lambda kv: -len(kv[1])))
    new_types = [m.name for f in pu.pr.files if f.status == "added" for m in f.members
                 if m.kind in ("class", "interface", "record", "enum")]
    parts = [f"{pu.stats['files']} files changed (+{pu.stats['additions']}/-{pu.stats['deletions']}; {cats})."]
    if new_types:
        parts.append(f"Introduces {len(new_types)} new type(s): {', '.join(new_types[:8])}{'...' if len(new_types) > 8 else ''}.")
    if impact.functional_areas:
        parts.append("Primary functional areas: " + ", ".join(area_name(a) for a in impact.functional_areas[:4]) + ".")
    if impact.apis:
        parts.append(f"{len(impact.apis)} API endpoint(s) affected.")
    return " ".join(parts)


def _ai_synthesis(llm: LLMProvider, pu: PRUnderstanding, issues: list[JiraIssue], impact: ImpactReport,
                  traces: list[RequirementTrace]) -> tuple[str | None, list[str], list[str]]:
    if not llm.available:
        return None, [], []
    diff_excerpt = []
    budget = 24000
    for f in pu.pr.files:
        if f.patch and f.category in ("code", "config", "ui", "migration"):
            chunk = f"--- {f.path} ({f.status})\n{truncate(f.patch, 3000)}\n"
            if budget - len(chunk) < 0:
                break
            budget -= len(chunk)
            diff_excerpt.append(chunk)
    reqs = "\n".join(f"{i.key} [{i.issue_type}/{i.status}] {i.summary}\n{truncate(i.description, 2500)}" for i in issues)
    prompt = (
        f"PR {pu.pr.repo}#{pu.pr.number}: {pu.pr.title}\n\nPR description:\n{truncate(pu.pr.body, 3000)}\n\n"
        f"Linked Jira requirements:\n{reqs or '(none readable)'}\n\n"
        f"Deterministic impact analysis:\n{json.dumps({'areas': impact.functional_areas, 'apis': impact.apis[:15], 'classes': impact.classes[:25], 'feature_flags': impact.feature_flags[:10], 'config': impact.config[:10], 'dependents': impact.dependents[:15], 'risk_factors': impact.risk_factors}, indent=1)}\n\n"
        f"Diff excerpt:\n{''.join(diff_excerpt)}\n\n"
        'Return {"summary": "<4-6 sentence technical summary of what changed and why>", '
        '"requirements": [{"key": "...", "alignment": "aligned|partial|misaligned|unclear", "notes": "..."}], '
        '"concerns": ["<specific, evidence-backed review concern>", ...], '
        '"test_focus": ["<behaviour that regression tests must cover>", ...]}'
    )
    answer = llm.complete_json(
        "You are a principal engineer and QE architect reviewing a pull request for Conga CLM (contract lifecycle "
        "management). Be specific and only state what the evidence supports.", prompt, max_tokens=1800)
    if not answer:
        return None, ["AI synthesis unavailable (LLM call failed); deterministic analysis used."], []
    for item in answer.get("requirements", []):
        for t in traces:
            if t.key == item.get("key") and t.found:
                t.alignment = item.get("alignment", t.alignment)
                t.notes = item.get("notes", t.notes)
    notes = [f"Regression focus: {x}" for x in answer.get("test_focus", [])[:6]]
    concerns = [c for c in answer.get("concerns", [])[:5] if isinstance(c, str)]
    return answer.get("summary"), notes, concerns


def run_pr_quality(settings: Settings, github: Any, jira: Any | None, llm: LLMProvider, repo: str, number: int,
                   layer: IntelligenceLayer | None = None, execute: bool = False) -> PRQualityReport:
    pr = github.get_pull_request(repo, number)
    pu = understand_pr(pr)
    layer = layer or IntelligenceLayer.load(settings.index_dir, [r.name for r in settings.dev_repos],
                                            settings.automation_repo.name, settings.knowledge_file)

    traces: list[RequirementTrace] = []
    issues: list[JiraIssue] = []
    for key in pu.jira_keys[:5]:
        if jira is None:
            traces.append(RequirementTrace(key=key, found=False, error="Jira not configured (JIRA_EMAIL/JIRA_API_TOKEN)",
                                           url=f"{settings.jira_base_url}/browse/{key}"))
            continue
        trace, issue = _trace_requirement(key, jira, pu)
        traces.append(trace)
        if issue:
            issues.append(issue)

    impact = analyze_pr_impact(pu, layer, issues)
    ai_summary, ai_notes, concerns = _ai_synthesis(llm, pu, issues, impact, traces)

    high_risk = impact.risk_score >= settings.gate.high_risk_score
    selected = select_tests(impact, pu.terms, layer.tests, settings.execution.max_tests, high_risk=high_risk)
    new_types = [m.name for f in pr.files if f.category == "code" for m in f.members
                 if m.kind in ("class", "record") and f.status == "added"]
    gaps = find_test_gaps(impact, layer.tests, selected, new_types, pu.files_by_category.get("test", []))

    framework = layer.tests.primary_framework if layer.tests else "unknown"
    execution = run_tests(selected, settings.execution, framework, execute, github, f"{repo.split('/')[-1]}-{number}")
    summary = ai_summary or _heuristic_summary(pu, impact)
    if execution.results:
        analyze_failures(execution.results, llm, summary)

    gate = decide(impact, pu.jira_keys, [t.key for t in traces if t.found], selected, execution, gaps,
                  settings.gate, concerns)
    return PRQualityReport(
        understanding=pu, requirements=traces, impact=impact, selected=selected, gaps=gaps, execution=execution,
        gate=gate, change_summary=summary, ai_used=ai_summary is not None, ai_notes=ai_notes,
        layer_status=layer.status(), generated_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        framework=framework, dry_run=not settings.post,
    )
