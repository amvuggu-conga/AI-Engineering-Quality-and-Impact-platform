"""JUnit/xUnit XML result parsing (TestNG, Surefire, NUnit-JUnit logger, Playwright, pytest all emit it)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ..models import TestResult


def parse_junit_xml(content: str | bytes) -> list[TestResult]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    results: list[TestResult] = []
    for case in root.iter("testcase"):
        classname = case.get("classname") or ""
        name = case.get("name") or ""
        status, message, details = "passed", None, None
        for tag, st in (("failure", "failed"), ("error", "error"), ("skipped", "skipped")):
            el = case.find(tag)
            if el is not None:
                status = st
                text = (el.text or "").strip()
                message = el.get("message") or (text.splitlines()[0] if text else None)
                details = text[:4000] or None
                break
        try:
            duration = float(case.get("time") or 0)
        except ValueError:
            duration = 0.0
        results.append(TestResult(id=f"{classname}.{name}" if classname else name, name=name, status=status,
                                  duration_s=duration, message=message, details=details))
    return results


def parse_junit_glob(root: str | Path, pattern: str) -> list[TestResult]:
    out: list[TestResult] = []
    for p in sorted(Path(root).glob(pattern)):
        out.extend(parse_junit_xml(p.read_bytes()))
    return out


def match_result(test_id: str, results: dict[str, TestResult]) -> TestResult | None:
    if test_id in results:
        return results[test_id]
    alt = test_id.replace("#", ".")
    if alt in results:
        return results[alt]
    tail = test_id.split("::")[-1].split("#")[-1].split(".")[-1]
    for rid, r in results.items():
        if rid.endswith("." + tail) or r.name == tail:
            return r
    return None
