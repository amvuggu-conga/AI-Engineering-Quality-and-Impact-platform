"""Core data model shared by both tracks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Decision(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


@dataclass
class ChangedMember:
    kind: str  # class | interface | method | property | enum | record
    name: str
    file: str
    container: str | None = None

    @property
    def qualified(self) -> str:
        return f"{self.container}.{self.name}" if self.container else self.name


@dataclass
class ChangedFile:
    path: str
    status: str  # added | modified | removed | renamed
    additions: int = 0
    deletions: int = 0
    patch: str | None = None
    previous_path: str | None = None
    category: str = "code"  # code | test | config | build | docs | ui | migration | other
    members: list[ChangedMember] = field(default_factory=list)


@dataclass
class PullRequest:
    repo: str
    number: int
    title: str
    body: str
    author: str
    head_sha: str
    base_ref: str
    head_ref: str
    url: str
    files: list[ChangedFile] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)


@dataclass
class JiraIssue:
    key: str
    summary: str
    issue_type: str
    status: str
    priority: str | None
    description: str
    components: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    fix_versions: list[str] = field(default_factory=list)
    affected_versions: list[str] = field(default_factory=list)
    reporter: str | None = None
    assignee: str | None = None
    created: str | None = None
    resolution: str | None = None
    customer_fields: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    comments: list[str] = field(default_factory=list)
    issue_links: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ApiEndpoint:
    method: str
    route: str
    controller: str
    action: str
    file: str


@dataclass
class TestCase:
    __test__ = False

    id: str  # stable identifier usable for execution filters
    name: str
    file: str
    framework: str
    suite: str | None = None
    tags: list[str] = field(default_factory=list)
    areas: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass
class SelectedTest:
    test: TestCase
    score: float
    reasons: list[str]


@dataclass
class TestResult:
    __test__ = False

    id: str
    name: str
    status: str  # passed | failed | skipped | error
    duration_s: float = 0.0
    message: str | None = None
    details: str | None = None
    classification: str | None = None  # product-regression | environment | test-data | flaky | unknown


@dataclass
class ExecutionSummary:
    executor: str
    executed: bool
    run_url: str | None = None
    results: list[TestResult] = field(default_factory=list)
    note: str | None = None

    @property
    def counts(self) -> dict[str, int]:
        out = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
        for r in self.results:
            out[r.status] = out.get(r.status, 0) + 1
        return out


@dataclass
class SimilarDefect:
    key: str
    summary: str
    score: float
    status: str | None = None
    url: str | None = None
    components: list[str] = field(default_factory=list)
    customer: str | None = None


@dataclass
class DocReference:
    title: str
    url: str
    area: str | None = None
    score: float = 0.0


@dataclass
class ImpactReport:
    functional_areas: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    apis: list[str] = field(default_factory=list)
    config: list[str] = field(default_factory=list)
    feature_flags: list[str] = field(default_factory=list)
    workflows: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)
    data_migrations: list[str] = field(default_factory=list)
    customer_impact: list[str] = field(default_factory=list)
    similar_defects: list[SimilarDefect] = field(default_factory=list)
    docs: list[DocReference] = field(default_factory=list)
    risk_score: int = 0
    risk_factors: list[str] = field(default_factory=list)


@dataclass
class TestGap:
    __test__ = False

    area: str
    reason: str
    severity: str = "medium"  # low | medium | high


@dataclass
class GateResult:
    decision: Decision
    reasons: list[str]
    evidence: list[str] = field(default_factory=list)


@dataclass
class CodeCandidate:
    file: str
    score: float
    reasons: list[str]
    symbols: list[str] = field(default_factory=list)
    repo: str | None = None


def to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, list):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj
