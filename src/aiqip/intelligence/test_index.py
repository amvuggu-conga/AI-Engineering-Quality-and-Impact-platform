"""Test intelligence: discover automation tests and map them to functional areas and APIs.

The CLM automation repo (congaengr/rlpclm-automation) framework is detected automatically;
supported: Java TestNG/JUnit, C# NUnit/MSTest/xUnit, TypeScript/JavaScript Playwright/Jest/
Mocha/Cypress, Python pytest and Gherkin (Cucumber/SpecFlow/Reqnroll) feature files.

An optional ``aiqip-test-map.yaml`` at the automation repo root (or ``--mapping``) lets QE pin
tests to areas/endpoints explicitly::

    rules:
      - match: "**/Agreement*/**"     # glob on file path, or
        tag: "smoke"                  # tag/group/category, or
        name: "(?i)generate.*doc"     # regex on test id
        areas: [document-generation]
        endpoints: ["/api/clm/v1/agreements/{id}/generate"]
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from ..models import TestCase
from ..taxonomy import classify
from ..text import BM25Index, tokenize
from .csharp import STRING_ROUTE_RE

SKIP_DIRS = {".git", "node_modules", "bin", "obj", "target", "build", "dist", ".venv", "venv", "__pycache__",
             "test-results", "allure-results", "reports", "playwright-report", ".idea", ".vs"}

JAVA_TEST_RE = re.compile(r"@Test\b(\s*\((?P<args>[^)]*)\))?(?P<between>(?:\s*@\w+(?:\([^)]*\))?)*)\s*public\s+[\w<>\[\]]+\s+(?P<name>\w+)\s*\(")
JAVA_GROUPS_RE = re.compile(r"groups\s*=\s*(?:\{([^}]*)\}|(\"[^\"]*\"))")
JAVA_DESC_RE = re.compile(r"description\s*=\s*\"([^\"]*)\"")
JAVA_PKG_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
JAVA_CLASS_RE = re.compile(r"\bclass\s+(\w+)")
CS_TEST_RE = re.compile(r"(?P<attrs>(?:\s*\[[^\]]+\]\s*)+)\s*public\s+(?:async\s+)?[\w<>]+\s+(?P<name>\w+)\s*\(")
CS_TEST_ATTRS = ("Test", "TestCase", "TestMethod", "Fact", "Theory", "DataTestMethod", "TestCaseSource")
CS_CATEGORY_RE = re.compile(r"(?:Category|TestCategory|Trait)\(\s*\"([^\"]+)\"(?:\s*,\s*\"([^\"]+)\")?")
CS_NS_RE = re.compile(r"^\s*namespace\s+([\w.]+)", re.M)
JS_TEST_RE = re.compile(r"^\s*(?:test|it)(?:\.only|\.skip)?\s*\(\s*([`'\"])(?P<name>.+?)\1", re.M)
JS_DESCRIBE_RE = re.compile(r"^\s*(?:test\.)?describe(?:\.serial|\.parallel|\.only)?\s*\(\s*([`'\"])(?P<name>.+?)\1", re.M)
PY_TEST_RE = re.compile(r"(?P<decor>(?:^\s*@[\w.]+(?:\([^)]*\))?\s*\n)*)^\s*(?:async\s+)?def\s+(?P<name>test_\w+)\s*\(", re.M)
PY_MARK_RE = re.compile(r"@pytest\.mark\.(\w+)")
GHERKIN_SCENARIO_RE = re.compile(r"^\s*Scenario(?: Outline| Template)?:\s*(.+)$", re.M)
GHERKIN_FEATURE_RE = re.compile(r"^\s*Feature:\s*(.+)$", re.M)
TAG_IN_TITLE_RE = re.compile(r"@([\w-]+)")


def _strip_quotes(s: str) -> list[str]:
    return [t.strip().strip("\"'") for t in s.split(",") if t.strip().strip("\"'")]


def _line_of(source: str, pos: int) -> int:
    return source.count("\n", 0, pos) + 1


def _segments(source: str, starts: list[int]) -> list[str]:
    bounds = starts + [len(source)]
    return [source[bounds[i]: bounds[i + 1]] for i in range(len(starts))]


def discover_tests(rel: str, source: str) -> list[dict[str, Any]]:
    """Return raw test records for one file: id, name, suite, tags, framework, body."""
    lower = rel.lower()
    out: list[dict[str, Any]] = []
    if lower.endswith(".java") and "@Test" in source:
        pkg_m = JAVA_PKG_RE.search(source)
        pkg = pkg_m.group(1) if pkg_m else ""
        cls_m = JAVA_CLASS_RE.search(source)
        cls = cls_m.group(1) if cls_m else Path(rel).stem
        matches = list(JAVA_TEST_RE.finditer(source))
        for m, body in zip(matches, _segments(source, [m.start() for m in matches])):
            args = m.group("args") or ""
            g = JAVA_GROUPS_RE.search(args)
            d = JAVA_DESC_RE.search(args)
            fq = f"{pkg}.{cls}" if pkg else cls
            out.append({"id": f"{fq}#{m.group('name')}", "name": m.group("name"), "suite": fq,
                        "tags": _strip_quotes(g.group(1) or g.group(2)) if g else [],
                        "description": d.group(1) if d else "",
                        "framework": "testng" if "org.testng" in source else "junit", "body": body})
    elif lower.endswith(".cs") and any(f"[{a}" in source for a in CS_TEST_ATTRS):
        ns = CS_NS_RE.search(source)
        cls_m = re.search(r"\bclass\s+(\w+)", source)
        cls = cls_m.group(1) if cls_m else Path(rel).stem
        fq = f"{ns.group(1)}.{cls}" if ns else cls
        class_tags = [a or b for a, b in CS_CATEGORY_RE.findall(source[: cls_m.start()] if cls_m else "")]
        matches = [m for m in CS_TEST_RE.finditer(source)
                   if any(re.search(rf"\b{a}\b", m.group("attrs")) for a in CS_TEST_ATTRS)]
        if "[TestMethod" in source or "[DataTestMethod" in source:
            framework = "mstest"
        elif "[Fact" in source or "[Theory" in source:
            framework = "xunit"
        else:
            framework = "nunit"
        for m, body in zip(matches, _segments(source, [m.start() for m in matches])):
            tags = class_tags + [b if a in ("Category", "TestCategory") and b else (b or a)
                                 for a, b in CS_CATEGORY_RE.findall(m.group("attrs"))]
            out.append({"id": f"{fq}.{m.group('name')}", "name": m.group("name"), "suite": fq, "tags": tags,
                        "description": "", "framework": framework, "body": body})
    elif lower.endswith((".ts", ".js", ".tsx", ".jsx", ".mjs")) and JS_TEST_RE.search(source):
        describes = [m.group("name") for m in JS_DESCRIBE_RE.finditer(source)]
        suite = " > ".join(describes[:1]) or Path(rel).stem
        framework = "playwright" if "@playwright/test" in source else "cypress" if "cy." in source else "jest"
        matches = list(JS_TEST_RE.finditer(source))
        for m, body in zip(matches, _segments(source, [m.start() for m in matches])):
            title = m.group("name")
            out.append({"id": f"{rel}::{title}", "name": title, "suite": suite,
                        "tags": TAG_IN_TITLE_RE.findall(title) + TAG_IN_TITLE_RE.findall(suite),
                        "description": "", "framework": framework, "body": body})
    elif lower.endswith(".py") and "def test_" in source:
        matches = list(PY_TEST_RE.finditer(source))
        for m, body in zip(matches, _segments(source, [m.start() for m in matches])):
            out.append({"id": f"{rel}::{m.group('name')}", "name": m.group("name"), "suite": Path(rel).stem,
                        "tags": PY_MARK_RE.findall(m.group("decor") or ""), "description": "",
                        "framework": "pytest", "body": body})
    elif lower.endswith(".feature"):
        feat = GHERKIN_FEATURE_RE.search(source)
        feature = feat.group(1).strip() if feat else Path(rel).stem
        feature_tags = TAG_IN_TITLE_RE.findall(source[: feat.start()]) if feat else []
        matches = list(GHERKIN_SCENARIO_RE.finditer(source))
        for m, body in zip(matches, _segments(source, [m.start() for m in matches])):
            prev = source[: m.start()].rstrip().splitlines()
            tags = TAG_IN_TITLE_RE.findall(prev[-1]) if prev and prev[-1].strip().startswith("@") else []
            out.append({"id": f"{rel}:{_line_of(source, m.start())}", "name": m.group(1).strip(), "suite": feature,
                        "tags": feature_tags + tags, "description": "", "framework": "gherkin", "body": body})
    return out


def load_mapping(path: Path | None) -> list[dict[str, Any]]:
    if path and path.exists():
        return (yaml.safe_load(path.read_text()) or {}).get("rules", [])
    return []


def _apply_mapping(test: dict[str, Any], rel: str, rules: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    areas: list[str] = []
    endpoints: list[str] = []
    for rule in rules:
        ok = True
        if "match" in rule:
            ok &= fnmatch.fnmatch(rel, rule["match"])
        if "tag" in rule:
            ok &= rule["tag"] in test["tags"]
        if "name" in rule:
            ok &= bool(re.search(rule["name"], test["id"]))
        if ok:
            areas.extend(rule.get("areas", []))
            endpoints.extend(rule.get("endpoints", []))
    return areas, endpoints


def build_test_index(repo_name: str, root: str | Path, mapping_path: str | Path | None = None) -> dict[str, Any]:
    root = Path(root)
    mapping = load_mapping(Path(mapping_path) if mapping_path else root / "aiqip-test-map.yaml")
    tests: list[dict[str, Any]] = []
    frameworks: Counter[str] = Counter()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.lower().endswith((".java", ".cs", ".ts", ".js", ".tsx", ".jsx", ".mjs", ".py", ".feature")):
                continue
            p = Path(dirpath) / fn
            rel = p.relative_to(root).as_posix()
            try:
                source = p.read_text(errors="replace")
            except OSError:
                continue
            for raw in discover_tests(rel, source):
                frameworks[raw["framework"]] += 1
                endpoints = sorted(set(STRING_ROUTE_RE.findall(raw["body"])))[:20]
                descriptor = " ".join([raw["name"], raw["suite"] or "", rel.replace("/", " "), " ".join(raw["tags"]),
                                       raw.get("description", "")])
                body_tokens = tokenize(raw["body"][:4000])
                areas = [a for a, _ in classify(tokenize(descriptor) * 3 + body_tokens, top_k=3)]
                m_areas, m_eps = _apply_mapping(raw, rel, mapping)
                areas = list(dict.fromkeys(m_areas + areas))
                endpoints = list(dict.fromkeys(m_eps + endpoints))
                keywords = [t for t, _ in Counter(tokenize(descriptor) * 2 + body_tokens).most_common(25)]
                tests.append({"id": raw["id"], "name": raw["name"], "file": rel, "framework": raw["framework"],
                              "suite": raw["suite"], "tags": raw["tags"], "areas": areas, "endpoints": endpoints,
                              "keywords": keywords})
    bm25 = BM25Index()
    for t in tests:
        bm25.add(t["id"], t["keywords"] + tokenize(" ".join([t["name"], t["suite"] or "", t["file"], " ".join(t["tags"])])) * 2)
    return {"repo": repo_name, "frameworks": dict(frameworks), "tests": tests, "bm25": bm25.to_dict()}


class TestIndex:
    __test__ = False

    def __init__(self, data: dict[str, Any]):
        self.repo = data.get("repo", "")
        self.frameworks: dict[str, int] = data.get("frameworks", {})
        self.tests = [TestCase(**{k: t.get(k) for k in TestCase.__dataclass_fields__ if k in t}) for t in data.get("tests", [])]
        self.by_id = {t.id: t for t in self.tests}
        self.bm25 = BM25Index.from_dict(data.get("bm25", {}))

    @classmethod
    def load(cls, path: str | Path) -> "TestIndex":
        return cls(json.loads(Path(path).read_text()))

    @property
    def primary_framework(self) -> str:
        return max(self.frameworks, key=self.frameworks.get) if self.frameworks else "unknown"

    def by_area(self, area: str) -> list[TestCase]:
        return [t for t in self.tests if area in t.areas]

    def area_coverage(self) -> dict[str, int]:
        c: Counter[str] = Counter()
        for t in self.tests:
            c.update(t.areas)
        return dict(c)
