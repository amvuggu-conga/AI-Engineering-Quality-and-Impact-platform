"""Product knowledge & business rules: Conga CLM documentation index."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import DocReference
from ..taxonomy import classify
from ..text import BM25Index, tokenize, truncate

BUNDLED_INDEX = Path(__file__).resolve().parents[3] / "data" / "knowledge" / "clm-docs-index.json"


def build_docs_index(pages: list[dict[str, Any]], source: str) -> dict[str, Any]:
    docs = []
    bm25 = BM25Index()
    for page in pages:
        text = "" if page.get("error") else page.get("text", "")
        descriptor = f"{page['title']} {page.get('section', '')}"
        areas = [a for a, _ in classify(tokenize(descriptor) * 3 + tokenize(text[:5000]), top_k=2)]
        doc = {"url": page["url"], "title": page["title"], "section": page.get("section", ""),
               "product": page.get("product", ""), "areas": areas, "has_content": bool(text),
               "summary": truncate(text, 400) if text else ""}
        docs.append(doc)
        bm25.add(page["url"], tokenize(descriptor) * 3 + tokenize(text[:8000]))
    return {"source": source, "count": len(docs), "docs": docs, "bm25": bm25.to_dict()}


class KnowledgeBase:
    def __init__(self, data: dict[str, Any] | None):
        data = data or {}
        self.docs = {d["url"]: d for d in data.get("docs", [])}
        self.bm25 = BM25Index.from_dict(data.get("bm25", {}))

    @classmethod
    def load(cls, path: str | Path | None) -> "KnowledgeBase":
        candidates = [Path(path)] if path else []
        candidates.append(BUNDLED_INDEX)
        for p in candidates:
            if p.exists():
                return cls(json.loads(p.read_text()))
        return cls(None)

    def __len__(self) -> int:
        return len(self.docs)

    def search(self, query: str | list[str], areas: list[str] | None = None, top_k: int = 5) -> list[DocReference]:
        hits = self.bm25.search(query, top_k=top_k * 8)
        best: dict[str, DocReference] = {}
        for url, score in hits:
            d = self.docs[url]
            if "release-notes" in url:
                score *= 0.5
            if "/preview/" in url:
                score *= 0.95
            boost = 1.3 if areas and set(d["areas"]) & set(areas) else 1.0
            ref = DocReference(title=d["title"], url=url, area=(d["areas"] or [None])[0], score=round(score * boost, 2))
            key = d["title"].lower()
            if key not in best or ref.score > best[key].score:
                best[key] = ref
        return sorted(best.values(), key=lambda r: r.score, reverse=True)[:top_k]
