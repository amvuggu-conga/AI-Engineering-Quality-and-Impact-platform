"""Use case 2 - Customer-Aware Agentic AI (Customer Track)."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from .. import __version__
from ..analysis.bug_understanding import BugUnderstanding, understand_bug
from ..analysis.impact import score_risk
from ..analysis.root_cause import locate_root_cause, suggest_owners
from ..analysis.test_selection import find_test_gaps, select_tests
from ..config import Settings
from ..intelligence.layer import IntelligenceLayer
from ..llm import LLMProvider
from ..models import CodeCandidate, ImpactReport, SelectedTest, TestGap
from ..taxonomy import area_name
from ..text import truncate


@dataclass
class BugAnalysisReport:
    bug: BugUnderstanding
    candidates: list[CodeCandidate]
    impact: ImpactReport
    selected: list[SelectedTest]
    gaps: list[TestGap]
    owners: list[tuple[str, int]]
    hypothesis: str
    confidence: str
    next_steps: list[str]
    ai_used: bool
    layer_status: dict[str, str]
    generated_at: str
    dry_run: bool = True
    version: str = __version__

    def to_json(self) -> dict[str, Any]:
        from ..models import to_dict
        i = self.bug.issue
        return {
            "version": self.version, "generated_at": self.generated_at, "dry_run": self.dry_run,
            "issue": {"key": i.key, "summary": i.summary, "status": i.status, "priority": i.priority, "url": i.url},
            "business_behavior": self.bug.business_behavior, "repro_steps": self.bug.repro_steps,
            "customer_context": self.bug.customer_context, "areas": self.bug.areas,
            "root_cause_hypothesis": self.hypothesis, "confidence": self.confidence,
            "code_candidates": to_dict(self.candidates), "impact": to_dict(self.impact),
            "regression_scope": [{"id": s.test.id, "score": s.score, "reasons": s.reasons} for s in self.selected],
            "test_gaps": to_dict(self.gaps), "suggested_owners": self.owners, "next_steps": self.next_steps,
            "ai_used": self.ai_used, "intelligence_layer": self.layer_status,
        }


def _impact_for_candidates(bug: BugUnderstanding, candidates: list[CodeCandidate], layer: IntelligenceLayer) -> ImpactReport:
    impact = ImpactReport()
    impact.functional_areas = [a for a, _ in bug.areas]
    for c in candidates[:5]:
        idx = layer.code.get(c.repo or "")
        info = idx.file(c.file) if idx else None
        impact.files.append(f"{c.repo}: {c.file}" if c.repo else c.file)
        if not info:
            continue
        types = [t["name"] for t in info.get("types", [])]
        impact.classes.extend(types)
        impact.apis.extend(f"{e['method']} {e['route']} ({e['controller']}.{e['action']})" for e in info.get("endpoints", []))
        impact.feature_flags.extend(info.get("feature_flags", [])[:5])
        impact.config.extend(info.get("config_keys", [])[:5])
        for name, users in idx.dependents(types, exclude={c.file}, limit=5).items():
            impact.dependents.extend(f"{name} <- {u}" for u in users[:3])
        for a in info.get("areas", []):
            if a not in impact.functional_areas:
                impact.functional_areas.append(a)
    impact.classes = list(dict.fromkeys(impact.classes))[:20]
    impact.apis = list(dict.fromkeys(impact.apis))[:15]
    impact.dependents = list(dict.fromkeys(impact.dependents))[:15]
    impact.functional_areas = impact.functional_areas[:5]
    impact.similar_defects = layer.defects.similar(bug.terms, impact.functional_areas, exclude={bug.issue.key}, top_k=5)
    impact.docs = layer.knowledge.search(bug.terms[:30], impact.functional_areas, top_k=3)
    impact.customer_impact = [f"{k}: {v}" for k, v in list(bug.customer_context.items())[:6]]
    score_risk(impact, None)
    return impact


def _heuristic_hypothesis(bug: BugUnderstanding, candidates: list[CodeCandidate]) -> tuple[str, str]:
    if not candidates:
        return ("Not enough code intelligence to localise the defect (no code index or no matching code). "
                "Index the dev repos with `aiqip index code` for code-level hypotheses.", "low")
    top = candidates[0]
    areas = ", ".join(area_name(a) for a, _ in bug.areas[:2]) or "an unclassified area"
    symbols = f" ({', '.join(top.symbols[:3])})" if top.symbols else ""
    text = (f"The reported behaviour falls in {areas}. The most likely location is `{top.file}`{symbols} in "
            f"{top.repo}, ranked first because: {'; '.join(top.reasons)}.")
    if bug.error_signatures:
        text += f" Error signature reported: `{truncate(bug.error_signatures[0], 120)}`."
    confidence = "medium" if top.score > 8 and len(top.reasons) > 1 else "low"
    return text, confidence


def run_bug_analysis(settings: Settings, jira: Any, github: Any | None, llm: LLMProvider, key: str,
                     layer: IntelligenceLayer | None = None) -> BugAnalysisReport:
    issue = jira.get_issue(key)
    bug = understand_bug(issue)
    layer = layer or IntelligenceLayer.load(settings.index_dir, [r.name for r in settings.dev_repos],
                                            settings.automation_repo.name, settings.knowledge_file)
    candidates = locate_root_cause(bug, layer, github, [r.name for r in settings.dev_repos])
    owners = suggest_owners(candidates, layer, github)
    impact = _impact_for_candidates(bug, candidates, layer)
    selected = select_tests(impact, bug.terms, layer.tests, min(settings.execution.max_tests, 60))
    gaps = find_test_gaps(impact, layer.tests, selected, [], [])
    hypothesis, confidence = _heuristic_hypothesis(bug, candidates)
    next_steps = [
        "Reproduce with the steps above in a non-production org matching the customer's version/config.",
        f"Inspect {candidates[0].file} first." if candidates else "Index dev repos to enable code localisation.",
        "Add an automated regression test for this scenario once fixed (see test gaps).",
    ]
    ai_used = False
    if llm.available:
        evidence = {
            "issue": {"key": issue.key, "summary": issue.summary, "priority": issue.priority,
                      "components": issue.components, "description": truncate(issue.description, 4000),
                      "comments": [truncate(c, 500) for c in issue.comments[:5]]},
            "customer_context": bug.customer_context, "error_signatures": bug.error_signatures,
            "code_candidates": [{"repo": c.repo, "file": c.file, "symbols": c.symbols, "why": c.reasons} for c in candidates[:6]],
            "similar_defects": [{"key": s.key, "summary": s.summary, "status": s.status} for s in impact.similar_defects],
            "docs": [{"title": d.title, "url": d.url} for d in impact.docs],
        }
        answer = llm.complete_json(
            "You are a senior Conga CLM support engineer and developer performing first-line root-cause analysis "
            "for a customer bug. Ground every statement in the evidence; say when evidence is insufficient.",
            f"Evidence:\n{json.dumps(evidence, indent=1)}\n\nReturn {{\"hypothesis\": \"<3-6 sentences>\", "
            "\"confidence\": \"low|medium|high\", \"next_steps\": [\"...\"]}", max_tokens=1200)
        if answer and answer.get("hypothesis"):
            hypothesis = answer["hypothesis"]
            confidence = answer.get("confidence", confidence)
            next_steps = [s for s in answer.get("next_steps", next_steps) if isinstance(s, str)][:6] or next_steps
            ai_used = True
    return BugAnalysisReport(
        bug=bug, candidates=candidates, impact=impact, selected=selected, gaps=gaps, owners=owners,
        hypothesis=hypothesis, confidence=confidence, next_steps=next_steps, ai_used=ai_used,
        layer_status=layer.status(), generated_at=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        dry_run=not settings.post,
    )
