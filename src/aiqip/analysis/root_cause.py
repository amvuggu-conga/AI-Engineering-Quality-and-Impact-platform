"""Root-cause localisation for a customer bug: rank likely code across the dev repos and
suggest the developer(s) to notify."""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from ..intelligence.layer import IntelligenceLayer
from ..models import CodeCandidate
from ..text import tokenize
from .bug_understanding import BugUnderstanding

log = logging.getLogger(__name__)


def locate_root_cause(bug: BugUnderstanding, layer: IntelligenceLayer, github: Any | None = None,
                      repos: list[str] | None = None, top_k: int = 8) -> list[CodeCandidate]:
    areas = {a for a, _ in bug.areas}
    idents = set(bug.identifiers)
    query = bug.terms[:40] + tokenize(bug.issue.summary) * 2
    candidates: list[CodeCandidate] = []
    for repo, idx in layer.code.items():
        for path, score in idx.search(query, top_k=top_k * 3, categories=("code", "ui", "config")):
            info = idx.file(path) or {}
            reasons = [f"text relevance {score:.1f}"]
            boost = 1.0
            file_areas = set(info.get("areas", []))
            if file_areas & areas:
                boost += 0.3
                reasons.append("same functional area: " + ", ".join(sorted(file_areas & areas)))
            types = {t["name"] for t in info.get("types", [])}
            named = (types | set(info.get("methods", []))) & idents
            if named:
                boost += 0.8
                reasons.append("bug mentions " + ", ".join(sorted(named)[:3]))
            ep_routes = [e["route"] for e in info.get("endpoints", [])]
            if any(r for r in bug.routes for e in ep_routes if r.rstrip("/").lower() in e.lower()):
                boost += 1.0
                reasons.append("serves an API route mentioned in the bug")
            symbols = sorted(types)[:4] + [m for m in info.get("methods", []) if m in idents][:3]
            candidates.append(CodeCandidate(path, round(score * boost, 2), reasons, symbols, repo))

    if not candidates and github is not None:
        terms = [t for t in bug.identifiers[:3]] or [w for w in bug.terms[:4]]
        for repo in repos or []:
            for term in terms:
                try:
                    for item in github.search_code(repo, term, max_results=10):
                        candidates.append(CodeCandidate(item["path"], 1.0, [f"GitHub code search hit for '{term}'"], [], repo))
                except Exception as exc:  # search is best-effort
                    log.info("GitHub code search failed for %s: %s", repo, exc)
                    break
        merged: dict[tuple[str, str], CodeCandidate] = {}
        for c in candidates:
            key = (c.repo or "", c.file)
            if key in merged:
                merged[key].score += 1.0
                merged[key].reasons.extend(r for r in c.reasons if r not in merged[key].reasons)
            else:
                merged[key] = c
        candidates = list(merged.values())

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:top_k]


def suggest_owners(candidates: list[CodeCandidate], layer: IntelligenceLayer, github: Any | None = None,
                   limit: int = 3) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for rank, c in enumerate(candidates[:5]):
        weight = 5 - rank
        idx = layer.code.get(c.repo or "")
        owners = idx.owners(c.file) if idx else []
        if not owners and github is not None and c.repo:
            try:
                owners = Counter(github.file_authors(c.repo, c.file, limit=20)).most_common(3)
            except Exception as exc:
                log.info("Could not read commit authors for %s: %s", c.file, exc)
        for author, n in owners[:3]:
            if re.search(r"\[bot\]|dependabot|github-actions", author, re.I):
                continue
            counter[author] += weight * max(1, n)
    return counter.most_common(limit)
