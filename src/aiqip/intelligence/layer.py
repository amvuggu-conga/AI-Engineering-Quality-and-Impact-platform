"""Unified AI Engineering Intelligence Layer: one facade over the four knowledge sources
(product knowledge, code intelligence, test intelligence, customer context/defects)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .code_index import CodeIndex
from .defects import DefectIndex
from .knowledge import KnowledgeBase
from .test_index import TestIndex


def index_file(index_dir: str | Path, kind: str, repo: str | None = None) -> Path:
    name = f"{kind}-{repo.replace('/', '__')}.json" if repo else f"{kind}.json"
    return Path(index_dir) / name


@dataclass
class IntelligenceLayer:
    code: dict[str, CodeIndex] = field(default_factory=dict)
    tests: TestIndex | None = None
    knowledge: KnowledgeBase = field(default_factory=lambda: KnowledgeBase(None))
    defects: DefectIndex = field(default_factory=lambda: DefectIndex(None))

    @classmethod
    def load(cls, index_dir: str | Path, dev_repos: list[str], automation_repo: str | None,
             knowledge_file: str | None = None) -> "IntelligenceLayer":
        layer = cls()
        for repo in dev_repos:
            p = index_file(index_dir, "code", repo)
            if p.exists():
                layer.code[repo] = CodeIndex.load(p)
        if automation_repo:
            p = index_file(index_dir, "tests", automation_repo)
            if p.exists():
                layer.tests = TestIndex.load(p)
        docs_path = Path(knowledge_file) if knowledge_file else index_file(index_dir, "docs")
        layer.knowledge = KnowledgeBase.load(docs_path)
        layer.defects = DefectIndex.load(index_file(index_dir, "defects"))
        return layer

    def status(self) -> dict[str, str]:
        return {
            "code": ", ".join(f"{r} ({len(c.files)} files)" for r, c in self.code.items()) or "not indexed",
            "tests": f"{self.tests.repo} ({len(self.tests.tests)} tests, {self.tests.primary_framework})"
            if self.tests else "not indexed",
            "knowledge": f"{len(self.knowledge)} CLM documentation pages" if len(self.knowledge) else "not indexed",
            "defects": f"{len(self.defects)} historical defects" if len(self.defects) else "not indexed",
        }
