"""Test Intelligence: regression selection (impacted tests) and test-gap detection."""

from __future__ import annotations

import re

from ..intelligence.test_index import TestIndex
from ..models import ImpactReport, SelectedTest, TestGap
from ..taxonomy import area_by_id, area_name
from ..text import tokenize

ALWAYS_TAGS = {"smoke", "sanity", "bvt", "critical", "p0"}


def _route_key(route: str) -> str:
    route = re.sub(r"\$\{[^}]+\}|\{[^}]+\}|:\w+", "*", route.lower())
    route = re.sub(r"/v\d+(\.\d+)?/", "/", route)
    return route.strip("/")


def _routes_match(a: str, b: str) -> bool:
    ka, kb = _route_key(a), _route_key(b)
    if not ka or not kb:
        return False
    sa, sb = [s for s in ka.split("/") if s not in ("*", "api")], [s for s in kb.split("/") if s not in ("*", "api")]
    if not sa or not sb:
        return False
    shorter, longer = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return len(shorter) >= 2 and all(s in longer for s in shorter)


def select_tests(impact: ImpactReport, terms: list[str], index: TestIndex | None, max_tests: int = 200,
                 high_risk: bool = False) -> list[SelectedTest]:
    if not index or not index.tests:
        return []
    area_weight = {a: (4.0 if i == 0 else 3.0 if i == 1 else 2.0) for i, a in enumerate(impact.functional_areas)}
    impacted_routes = [a.split(" ")[1] for a in impact.apis if " " in a]
    query = terms[:40] + tokenize(" ".join(impact.classes[:20])) * 2
    bm25 = dict(index.bm25.search(query, top_k=max(50, max_tests * 2)))
    top_bm25 = max(bm25.values()) if bm25 else 1.0

    selected: list[SelectedTest] = []
    for t in index.tests:
        score = 0.0
        reasons: list[str] = []
        overlap = [a for a in t.areas if a in area_weight]
        if overlap:
            score += sum(area_weight[a] for a in overlap)
            reasons.append("area: " + ", ".join(area_name(a) for a in overlap))
        ep_hits = [ep for ep in t.endpoints for r in impacted_routes if _routes_match(ep, r)]
        if ep_hits:
            score += 5.0
            reasons.append(f"calls impacted API {ep_hits[0]}")
        if t.id in bm25:
            rel = bm25[t.id] / top_bm25
            if rel > 0.25:
                score += 3.0 * rel
                reasons.append(f"keyword relevance {rel:.2f}")
        tags = {x.lower() for x in t.tags}
        if tags & ALWAYS_TAGS and (overlap or high_risk):
            score += 1.5
            reasons.append("smoke/critical tag")
        if score >= 3.0:
            selected.append(SelectedTest(t, round(score, 2), reasons))
    selected.sort(key=lambda s: s.score, reverse=True)
    return selected[:max_tests]


def find_test_gaps(impact: ImpactReport, index: TestIndex | None, selected: list[SelectedTest],
                   new_classes: list[str], pr_test_files: list[str]) -> list[TestGap]:
    gaps: list[TestGap] = []
    if not index:
        gaps.append(TestGap("automation", "Automation test index not available - regression scope could not be "
                            "selected. Run `aiqip index tests`.", "high"))
    else:
        coverage = index.area_coverage()
        for a in impact.functional_areas:
            if coverage.get(a, 0) == 0:
                area = area_by_id(a)
                sev = "high" if area and area.risk >= 3 else "medium"
                gaps.append(TestGap(area_name(a), "No automation tests mapped to this impacted functional area.", sev))
        has_endpoint_map = any(t.endpoints for t in index.tests)
        if has_endpoint_map:
            covered = {r for s in selected for r in s.test.endpoints}
            for api in impact.apis:
                if " " not in api or "[indirect]" in api:
                    continue
                route = api.split(" ")[1]
                if not any(_routes_match(route, c) for c in covered):
                    gaps.append(TestGap(api, "Impacted/new API endpoint has no automation test calling it.", "medium"))
    if new_classes and not pr_test_files:
        gaps.append(TestGap("unit tests", f"{len(new_classes)} new/changed type(s) without unit or integration tests "
                            f"in this PR (e.g. {', '.join(new_classes[:4])}).", "medium"))
    return gaps[:25]


def build_filter(selected: list[SelectedTest], framework: str) -> str:
    """Produce a framework-native test filter expression for the selected tests."""
    ids = [s.test.id for s in selected]
    fw = framework.lower()
    if fw in ("testng", "junit"):
        return ",".join(ids)  # mvn -Dtest=Class#method,Class#method
    if fw in ("nunit", "mstest", "xunit"):
        return "|".join(f"FullyQualifiedName={i}" for i in ids)  # dotnet test --filter
    if fw == "pytest":
        return " ".join(ids)
    if fw in ("playwright", "jest", "cypress"):
        names = sorted({re.escape(i.split("::", 1)[-1]) for i in ids})
        return "|".join(names)  # --grep
    if fw == "gherkin":
        return " ".join(ids)  # feature:line
    return ",".join(ids)
