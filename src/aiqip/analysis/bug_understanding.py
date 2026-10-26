"""Bug Understanding (Customer Track): business behavior, reproduction steps, customer context."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..models import JiraIssue
from ..taxonomy import classify
from ..text import tokenize

SECTION_RE = re.compile(
    r"^\s*(?:\*|#+|h\d\.)?\s*(steps?\s*to\s*reproduce|repro(?:duction)?\s*steps?|steps|expected(?:\s*(?:result|behaviou?r))?|"
    r"actual(?:\s*(?:result|behaviou?r))?|environment|workaround|description|summary|business impact|impact)\s*[:\-]?\s*\*?\s*$",
    re.I | re.M,
)
ERROR_RE = re.compile(r"((?:[A-Z]\w+)?(?:Exception|Error)\b[^\n]{0,160}|\b(?:HTTP\s*)?(?:4\d\d|5\d\d)\b[^\n]{0,80})")
ROUTE_RE = re.compile(r"(/(?:api|clm)[/\w{}\-.]*)")
IDENT_RE = re.compile(r"\b([A-Z][a-z]+(?:[A-Z][a-z0-9]+)+|[a-z]+(?:[A-Z][a-z0-9]+)+|[A-Za-z]+_[A-Za-z_]+)\b")


@dataclass
class BugUnderstanding:
    issue: JiraIssue
    business_behavior: str
    repro_steps: list[str]
    expected: str
    actual: str
    customer_context: dict[str, str]
    error_signatures: list[str]
    routes: list[str]
    identifiers: list[str]
    terms: list[str]
    areas: list[tuple[str, float]]
    sections: dict[str, str] = field(default_factory=dict)


def _sections(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    matches = list(SECTION_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        name = m.group(1).lower()
        key = ("steps" if name.startswith(("step", "repro")) else
               "expected" if name.startswith("expected") else
               "actual" if name.startswith("actual") else name)
        out[key] = text[m.end(): end].strip()
    return out


def _steps(text: str) -> list[str]:
    steps = []
    for line in text.splitlines():
        s = re.sub(r"^\s*(?:\d+[.)]|[-*#•])\s*", "", line).strip()
        if s:
            steps.append(s)
    return steps[:25]


def understand_bug(issue: JiraIssue) -> BugUnderstanding:
    text = issue.description or ""
    sections = _sections(text)
    steps_text = sections.get("steps", "")
    if not steps_text:
        numbered = [ln for ln in text.splitlines() if re.match(r"^\s*\d+[.)]\s+", ln)]
        steps_text = "\n".join(numbered)
    first_header = SECTION_RE.search(text)
    lead = text[: first_header.start()] if first_header and first_header.start() > 0 else text
    first_para = next((p.strip() for p in re.split(r"\n\s*\n", lead) if p.strip()), "")
    behavior = sections.get("description") or sections.get("summary") or first_para or issue.summary

    context = dict(issue.customer_fields)
    if issue.priority:
        context.setdefault("Priority", issue.priority)
    if issue.components:
        context.setdefault("Components", ", ".join(issue.components))
    if issue.affected_versions:
        context.setdefault("Affected versions", ", ".join(issue.affected_versions))
    if issue.labels:
        context.setdefault("Labels", ", ".join(issue.labels))
    if sections.get("environment"):
        context.setdefault("Environment", sections["environment"][:300])

    full = "\n".join([issue.summary, text, "\n".join(issue.comments[:5])])
    errors = list(dict.fromkeys(e.strip() for e in ERROR_RE.findall(full)))[:8]
    routes = list(dict.fromkeys(ROUTE_RE.findall(full)))[:10]
    idents = list(dict.fromkeys(IDENT_RE.findall(full)))[:30]

    c: Counter[str] = Counter()
    c.update(tokenize(issue.summary) * 4)
    c.update(tokenize(text))
    c.update(tokenize(" ".join(issue.components + issue.labels)) * 2)
    c.update(tokenize(" ".join(idents)) * 3)
    c.update(tokenize(" ".join(errors)) * 2)
    terms = [t for t, _ in c.most_common(60)]
    areas = classify(tokenize(issue.summary) * 3 + tokenize(text) + tokenize(" ".join(issue.components)) * 2, top_k=4)
    return BugUnderstanding(issue=issue, business_behavior=behavior.strip()[:1200], repro_steps=_steps(steps_text),
                            expected=sections.get("expected", "")[:600], actual=sections.get("actual", "")[:600],
                            customer_context=context, error_signatures=errors, routes=routes, identifiers=idents,
                            terms=terms, areas=areas, sections=sections)
