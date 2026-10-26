"""Impact Analysis: code, classes, methods, APIs, config, feature flags, workflows,
dependencies, and customer impact for a PR (or for a set of suspect files from a bug)."""

from __future__ import annotations

import re
from collections import Counter

from ..intelligence.csharp import (ATTR_RE, CONFIG_KEY_RE, CSPROJ_REF_RE, FLAG_CALL_RE, FLAG_CONST_RE,
                                   MINIMAL_API_RE, parse_csharp, parse_json_config)
from ..intelligence.layer import IntelligenceLayer
from ..models import ImpactReport, JiraIssue
from ..taxonomy import area_by_id, classify
from ..text import tokenize
from .diff import parse_patch
from .pr_understanding import PRUnderstanding

WORKFLOW_NAME_RE = re.compile(r"(Workflow|Flow|Job|Handler|Consumer|Subscriber|Listener|Callback|Orchestrat|Saga|"
                              r"Scheduler|Trigger|Queue|Event)", re.I)
DI_RE = re.compile(r"\.Add(Scoped|Transient|Singleton|HostedService)\s*<\s*([\w.]+)(?:\s*,\s*([\w.]+))?\s*>")


def _added_source(patch: str | None) -> str:
    return "\n".join(line for h in parse_patch(patch) for line in h.added)


def analyze_pr_impact(pu: PRUnderstanding, layer: IntelligenceLayer, jira: list[JiraIssue] | None = None) -> ImpactReport:
    pr = pu.pr
    report = ImpactReport()
    code_index = layer.code.get(pr.repo)
    changed_paths = {f.path for f in pr.files}
    report.files = [f.path for f in pr.files if f.category not in ("docs",)]

    classes: list[str] = list(pu.type_names)
    methods: list[str] = list(pu.method_names)
    apis: list[str] = []
    config: list[str] = []
    flags: list[str] = []
    workflows: list[str] = []
    deps: list[str] = []
    area_counter: Counter[str] = Counter()

    for area, score in pu.areas:
        area_counter[area] += score

    for f in pr.files:
        added = _added_source(f.patch)
        changed_text = "\n".join(line for h in parse_patch(f.patch) for line in h.added + h.removed)
        info = code_index.file(f.path) if code_index else None
        if info:
            classes.extend(t["name"] for t in info.get("types", []))
            area_counter.update({a: 2.0 for a in info.get("areas", [])})
        if f.path.lower().endswith(".cs"):
            source_for_routes = added if f.status == "added" else changed_text
            facts = parse_csharp(f.path, source_for_routes)
            if f.status == "added":
                classes.extend(t["name"] for t in facts.types)
            for ep in facts.endpoints:
                apis.append(f"{ep['method']} {ep['route']} ({ep['controller']}.{ep['action']})")
            for am in ATTR_RE.finditer(changed_text):
                if am.group(1) != "Route" and am.group(2) is not None and not facts.endpoints:
                    apis.append(f"{am.group(1).replace('Http', '').upper()} {am.group(2)} ({f.path.rsplit('/', 1)[-1]})")
            for mm in MINIMAL_API_RE.finditer(changed_text):
                apis.append(f"{mm.group(1).upper()} {mm.group(2)}")
            if info:
                for ep in info.get("endpoints", []):
                    if any(ep["action"] == m.name for m in f.members) or f.status == "added":
                        apis.append(f"{ep['method']} {ep['route']} ({ep['controller']}.{ep['action']})")
        for a, b in FLAG_CALL_RE.findall(changed_text):
            if (a or b) and len(a or b) > 2:
                flags.append(f"{a or b} ({f.path.rsplit('/', 1)[-1]})")
        for name, value in FLAG_CONST_RE.findall(changed_text):
            flags.append(f"{value} (const {name})")
        for groups in CONFIG_KEY_RE.findall(changed_text):
            for g in groups:
                if g:
                    config.append(f"{g} (read in {f.path.rsplit('/', 1)[-1]})")
        for kind, impl_a, impl_b in DI_RE.findall(changed_text):
            deps.append(f"DI registration ({kind}): {impl_a}{' -> ' + impl_b if impl_b else ''}")
        if f.category == "config":
            config.append(f"{f.path} ({f.status}, +{f.additions}/-{f.deletions})")
            if f.path.lower().endswith(".json"):
                cfg = parse_json_config(f.path, added if f.status == "added" else "{}")
                flags.extend(cfg.feature_flags)
        if f.category == "build":
            for kind, name in CSPROJ_REF_RE.findall(changed_text):
                deps.append(f"{kind}: {name} ({f.path})")
            if f.path.startswith(".github/workflows") or "pipeline" in f.path.lower():
                workflows.append(f"CI/CD pipeline: {f.path}")
        if f.category == "migration":
            report.data_migrations.append(f.path)
        stem = f.path.rsplit("/", 1)[-1]
        if WORKFLOW_NAME_RE.search(stem) and f.category in ("code", "ui"):
            workflows.append(f"{stem} ({f.status})")

    type_names = list(dict.fromkeys(c for c in classes if c))
    if code_index:
        dependents = code_index.dependents(type_names, exclude=changed_paths, limit=15)
        for name, users in dependents.items():
            for u in users[:8]:
                report.dependents.append(f"{name} <- {u}")
                area_counter.update({a: 0.5 for a in (code_index.file(u) or {}).get("areas", [])})
        for ep in code_index.endpoints_for_types(set(type_names), changed_paths):
            apis.append(f"{ep['method']} {ep['route']} ({ep['controller']}.{ep['action']}) [indirect]")
        for t in type_names:
            if t.startswith("I") and t[1:2].isupper():
                for impl in code_index.implementations(t):
                    report.dependents.append(f"{t} implemented by {impl}")
    # cross-repo: UI calls into changed API routes
    for repo, idx in layer.code.items():
        if repo == pr.repo or idx.kind != "ui":
            continue
        api_routes = {re.sub(r"\{[^}]+\}", "", a.split(" ")[1]).rstrip("/") for a in apis if " " in a}
        for path, info in idx.files.items():
            for consumed in info.get("consumed_endpoints", []):
                norm = re.sub(r"\$\{[^}]+\}|\{[^}]+\}", "", consumed).rstrip("/")
                if norm and any(r and (norm.endswith(r) or r.endswith(norm)) for r in api_routes if len(r) > 5):
                    report.dependents.append(f"UI {repo}: {path} calls {consumed}")

    for issue in jira or []:
        for area, score in classify(f"{issue.summary} {issue.description} {' '.join(issue.components)}", top_k=3):
            area_counter[area] += score

    report.classes = type_names[:60]
    report.methods = list(dict.fromkeys(methods))[:80]
    report.apis = list(dict.fromkeys(apis))[:40]
    report.config = list(dict.fromkeys(config))[:40]
    report.feature_flags = list(dict.fromkeys(flags))[:40]
    report.workflows = list(dict.fromkeys(workflows))[:30]
    report.dependencies = list(dict.fromkeys(deps))[:30]
    report.dependents = list(dict.fromkeys(report.dependents))[:40]
    report.functional_areas = [a for a, s in area_counter.most_common(6) if s >= 2.0]

    query = pu.terms[:40] + tokenize(pr.title) * 2
    exclude = set(pu.jira_keys)
    report.similar_defects = layer.defects.similar(query, report.functional_areas, exclude=exclude, top_k=5)
    report.docs = layer.knowledge.search(tokenize(pr.title) * 3 + pu.terms[:25], report.functional_areas, top_k=4)

    for issue in jira or []:
        cust = ", ".join(f"{k}: {v}" for k, v in list(issue.customer_fields.items())[:3])
        report.customer_impact.append(f"Requirement {issue.key} ({issue.issue_type}, priority {issue.priority or 'n/a'})"
                                      + (f" - {cust}" if cust else ""))
    for d in report.similar_defects[:3]:
        report.customer_impact.append(f"Historical defect {d.key} in a related area: {d.summary}")
    for a in report.functional_areas:
        area = area_by_id(a)
        if area and area.risk >= 3:
            report.customer_impact.append(f"Customer-critical capability touched: {area.name}")

    score_risk(report, pu)
    return report


def score_risk(report: ImpactReport, pu: PRUnderstanding | None) -> None:
    score = 0
    factors: list[str] = []
    risks = [area_by_id(a).risk for a in report.functional_areas if area_by_id(a)]
    if risks:
        score += max(risks) * 10
        factors.append(f"highest functional-area criticality {max(risks)}/3")
    if pu:
        size = pu.stats.get("additions", 0) + pu.stats.get("deletions", 0)
        score += min(20, size // 150)
        if size > 1000:
            factors.append(f"large change ({size} lines)")
        if not pu.files_by_category.get("test"):
            score += 10
            factors.append("no unit/integration test changes in the PR")
        if pu.truncated_patches:
            factors.append(f"{len(pu.truncated_patches)} file patch(es) too large for GitHub to return; analysed by name only")
    if report.apis:
        score += 10
        factors.append(f"{len(report.apis)} API endpoint(s) affected")
    if report.dependents:
        score += min(15, len(report.dependents))
        factors.append(f"{len(report.dependents)} dependent component(s)")
    if report.config or report.feature_flags:
        score += 5
        factors.append("configuration / feature-flag change")
    if report.data_migrations:
        score += 10
        factors.append("data migration")
    if "security-permissions" in report.functional_areas:
        score += 10
        factors.append("security / permissions area")
    if report.similar_defects:
        score += min(15, 5 * len(report.similar_defects))
        factors.append(f"{len(report.similar_defects)} similar historical customer defect(s)")
    report.risk_score = min(100, score)
    report.risk_factors = factors
