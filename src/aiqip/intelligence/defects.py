"""Customer context & historical defects (escape defects / customer bugs from Jira)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import SimilarDefect
from ..taxonomy import classify
from ..text import BM25Index, adf_to_text, tokenize, truncate


def defect_from_api(issue: dict[str, Any], base_url: str) -> dict[str, Any]:
    f = issue.get("fields", {})
    desc = f.get("description")
    desc_text = adf_to_text(desc) if isinstance(desc, (dict, list)) else (desc or "")
    text = f"{f.get('summary', '')}\n{desc_text}"
    return {
        "key": issue["key"],
        "summary": f.get("summary", ""),
        "description": truncate(desc_text, 1500),
        "status": (f.get("status") or {}).get("name"),
        "priority": (f.get("priority") or {}).get("name"),
        "components": [c.get("name", "") for c in f.get("components") or []],
        "labels": f.get("labels") or [],
        "created": f.get("created"),
        "resolution": (f.get("resolution") or {}).get("name") if f.get("resolution") else None,
        "fix_versions": [v.get("name", "") for v in f.get("fixVersions") or []],
        "areas": [a for a, _ in classify(text, top_k=2)],
        "url": f"{base_url.rstrip('/')}/browse/{issue['key']}",
    }


def build_defect_index(issues: list[dict[str, Any]], base_url: str, jql: list[str]) -> dict[str, Any]:
    defects = [defect_from_api(i, base_url) for i in issues]
    bm25 = BM25Index()
    for d in defects:
        bm25.add(d["key"], tokenize(d["summary"]) * 3 + tokenize(d["description"]) +
                 tokenize(" ".join(d["components"] + d["labels"])) * 2)
    return {"jql": jql, "count": len(defects), "defects": defects, "bm25": bm25.to_dict()}


class DefectIndex:
    def __init__(self, data: dict[str, Any] | None):
        data = data or {}
        self.defects = {d["key"]: d for d in data.get("defects", [])}
        self.bm25 = BM25Index.from_dict(data.get("bm25", {}))

    @classmethod
    def load(cls, path: str | Path) -> "DefectIndex":
        p = Path(path)
        return cls(json.loads(p.read_text()) if p.exists() else None)

    def __len__(self) -> int:
        return len(self.defects)

    def similar(self, query: str | list[str], areas: list[str] | None = None, exclude: set[str] | None = None,
                top_k: int = 5, min_score: float = 2.0) -> list[SimilarDefect]:
        exclude = exclude or set()
        out = []
        for key, score in self.bm25.search(query, top_k=top_k * 4, min_score=min_score):
            if key in exclude:
                continue
            d = self.defects[key]
            boost = 1.25 if areas and set(d["areas"]) & set(areas) else 1.0
            out.append(SimilarDefect(key=key, summary=d["summary"], score=round(score * boost, 2), status=d.get("status"),
                                     url=d.get("url"), components=d.get("components", [])))
        out.sort(key=lambda s: s.score, reverse=True)
        return out[:top_k]

    def area_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in self.defects.values():
            for a in d["areas"]:
                counts[a] = counts.get(a, 0) + 1
        return counts
