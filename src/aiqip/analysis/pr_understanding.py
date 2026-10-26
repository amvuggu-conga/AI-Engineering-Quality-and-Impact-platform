"""PR Understanding (Development Track): code changes, Jira requirement keys, changed functional areas."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..intelligence.csharp import classify_path
from ..models import ChangedMember, PullRequest
from ..taxonomy import classify
from ..text import extract_jira_keys, tokenize
from .diff import changed_members, parse_patch


@dataclass
class PRUnderstanding:
    pr: PullRequest
    jira_keys: list[str]
    files_by_category: dict[str, list[str]]
    members: list[ChangedMember]
    added_test_files: list[str]
    terms: list[str]
    areas: list[tuple[str, float]]
    stats: dict[str, int] = field(default_factory=dict)
    truncated_patches: list[str] = field(default_factory=list)

    @property
    def type_names(self) -> list[str]:
        names = [m.name for m in self.members if m.kind in ("class", "interface", "record", "struct", "enum")]
        names += [m.container for m in self.members if m.container]
        return list(dict.fromkeys(n for n in names if n))

    @property
    def method_names(self) -> list[str]:
        return [m.qualified for m in self.members if m.kind == "method"]


def understand_pr(pr: PullRequest, jira_projects: list[str] | None = None) -> PRUnderstanding:
    by_cat: dict[str, list[str]] = {}
    members: list[ChangedMember] = []
    truncated: list[str] = []
    term_counter: Counter[str] = Counter()
    for f in pr.files:
        f.category = classify_path(f.path)
        by_cat.setdefault(f.category, []).append(f.path)
        if f.patch is None and (f.additions + f.deletions) > 0:
            truncated.append(f.path)
        f.members = changed_members(f.path, f.patch)
        members.extend(f.members)
        term_counter.update(tokenize(f.path.replace("/", " ")) * 2)
        for h in parse_patch(f.patch):
            term_counter.update(tokenize(" ".join(h.added[:200] + h.removed[:50])))
    for m in members:
        term_counter.update(tokenize(m.name) * 3)
    narrative = " ".join([pr.title, pr.body, " ".join(pr.commits), pr.head_ref])
    term_counter.update(tokenize(narrative) * 3)

    jira_keys = extract_jira_keys(pr.title, pr.body, pr.head_ref, *pr.commits, projects=jira_projects)
    terms = [t for t, _ in term_counter.most_common(120)]
    areas = classify(tokenize(f"{pr.title} {pr.title} {pr.body}") * 2 + terms, top_k=5)
    return PRUnderstanding(
        pr=pr,
        jira_keys=jira_keys,
        files_by_category=by_cat,
        members=members,
        added_test_files=[f.path for f in pr.files if f.category == "test" and f.status == "added"],
        terms=terms,
        areas=areas,
        stats={"files": len(pr.files), "additions": sum(f.additions for f in pr.files),
               "deletions": sum(f.deletions for f in pr.files)},
        truncated_patches=truncated,
    )
