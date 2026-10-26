"""Failure analysis: classify failed tests as product regression vs environment / test maintenance / data."""

from __future__ import annotations

import json
import re

from ..llm import LLMProvider
from ..models import TestResult

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("environment", re.compile(r"timed? ?out|timeout|connection (refused|reset)|ECONN|ETIMEDOUT|socket|502|503|504|"
                               r"bad gateway|service unavailable|name or service not known|no such host|"
                               r"session not created|unable to connect|net::ERR|sso|login failed|token expired", re.I)),
    ("test-maintenance", re.compile(r"NoSuchElement|StaleElement|ElementNotInteractable|locator|selector|"
                                    r"element (is )?not (visible|found|clickable)|waiting for (locator|selector)", re.I)),
    ("test-data", re.compile(r"test data|record (not found|does not exist)|duplicate (key|value)|already exists|"
                             r"no rows|seed", re.I)),
    ("product-regression", re.compile(r"assert|expected .* (but|to) |should (be|have|equal)|NullReference|"
                                      r"status code (4\d\d|500)|500 internal|validation (failed|error)|"
                                      r"InvalidOperation|unexpected", re.I)),
]


def classify_failure(result: TestResult) -> str:
    text = f"{result.message or ''}\n{(result.details or '')[:1500]}"
    for label, pattern in PATTERNS:
        if pattern.search(text):
            return label
    return "unknown"


def analyze_failures(results: list[TestResult], llm: LLMProvider, change_summary: str) -> list[TestResult]:
    failed = [r for r in results if r.status in ("failed", "error")]
    for r in failed:
        r.classification = classify_failure(r)
    if failed and llm.available:
        payload = [{"id": r.id, "message": (r.message or "")[:300], "details": (r.details or "")[:800],
                    "heuristic": r.classification} for r in failed[:30]]
        answer = llm.complete_json(
            "You are a senior QE engineer triaging regression failures for a pull request. Classify each failure as "
            "one of: product-regression, environment, test-maintenance, test-data, flaky, unknown. A failure is a "
            "product-regression only if it plausibly relates to the code change.",
            f"Change summary:\n{change_summary[:2000]}\n\nFailures:\n{json.dumps(payload, indent=1)}\n\n"
            'Return {"classifications": [{"id": "...", "classification": "...", "reason": "..."}]}')
        for item in (answer or {}).get("classifications", []):
            for r in failed:
                if r.id == item.get("id") and item.get("classification"):
                    r.classification = item["classification"]
                    if item.get("reason"):
                        r.message = f"{r.message or ''} [AI triage: {item['reason']}]".strip()
    return results
