"""Render the PR Quality report as a GitHub PR comment (markdown) and a commit status/check."""

from __future__ import annotations

from ..connectors.github import COMMENT_MARKER
from ..execution.junit import match_result
from ..models import Decision
from ..taxonomy import area_name
from ..workflows.pr_quality import PRQualityReport

ICON = {Decision.PASS: "🟢", Decision.REVIEW: "🟡", Decision.BLOCK: "🔴"}
STATUS_ICON = {"passed": "✅", "failed": "❌", "error": "❌", "skipped": "⏭️"}


def _list(items: list[str], limit: int = 12, empty: str = "_None detected._") -> str:
    if not items:
        return empty
    lines = [f"- {i}" for i in items[:limit]]
    if len(items) > limit:
        lines.append(f"- _...and {len(items) - limit} more_")
    return "\n".join(lines)


def _code(items: list[str]) -> list[str]:
    return [f"`{i}`" for i in items]


def render_pr_comment(r: PRQualityReport) -> str:
    pu = r.understanding
    pr = pu.pr
    d = r.gate.decision
    out: list[str] = [COMMENT_MARKER]
    out.append(f"## {ICON[d]} AI Quality Gate: **{d.value}**")
    out.append(f"**{pr.repo}#{pr.number}** - {pr.title}  ")
    out.append(f"Risk score **{r.impact.risk_score}/100** · {pu.stats['files']} files "
               f"(+{pu.stats['additions']}/-{pu.stats['deletions']}) · head `{pr.head_sha[:10]}`")
    out.append("")
    out.append("### Recommendation")
    out.append(_list(r.gate.reasons, 10))
    if r.gate.evidence:
        out.append("")
        out.append("<sub>Evidence: " + " ".join(r.gate.evidence) + "</sub>")

    out.append("\n### Change summary")
    out.append(r.change_summary + ("" if r.ai_used else "  \n<sub>(deterministic summary - no LLM configured)</sub>"))

    out.append("\n### Jira traceability")
    if not r.requirements:
        out.append("⚠️ No Jira key found in the PR title, body, branch or commits.")
    else:
        out.append("| Ticket | Type / Status | Summary | Alignment |")
        out.append("|---|---|---|---|")
        for t in r.requirements:
            if t.found:
                out.append(f"| [{t.key}]({t.url}) | {t.issue_type} / {t.status} | {t.summary} | "
                           f"**{t.alignment}** - {t.notes} |")
            else:
                out.append(f"| [{t.key}]({t.url}) | - | _not readable_ | {t.error or ''} |")

    imp = r.impact
    out.append("\n### Change impact")
    out.append("**Functional areas:** " + (", ".join(area_name(a) for a in imp.functional_areas) or "_unclassified_"))
    if imp.risk_factors:
        out.append("**Risk factors:** " + "; ".join(imp.risk_factors))
    sections = [
        ("Classes / types", _code(imp.classes), 15),
        ("Methods", _code(imp.methods), 15),
        ("APIs", _code(imp.apis), 15),
        ("Configuration", _code(imp.config), 10),
        ("Feature flags", _code(imp.feature_flags), 10),
        ("Workflows / async", imp.workflows, 10),
        ("Dependencies", imp.dependencies, 10),
        ("Dependents (blast radius)", _code(imp.dependents), 12),
        ("Data migrations", _code(imp.data_migrations), 10),
        ("Customer impact", imp.customer_impact, 8),
    ]
    for title, items, limit in sections:
        if items:
            out.append(f"<details><summary><b>{title}</b> ({len(items)})</summary>\n\n{_list(items, limit)}\n\n</details>")
    if imp.similar_defects:
        out.append("\n**Related historical customer defects**")
        out.append(_list([f"[{s.key}]({s.url}) {s.summary} ({s.status or 'n/a'})" for s in imp.similar_defects], 5))
    if imp.docs:
        out.append("\n**Product knowledge (business rules)**")
        out.append(_list([f"[{doc.title}]({doc.url})" for doc in imp.docs], 4))

    out.append("\n### Regression scope & results")
    ex = r.execution
    c = ex.counts
    if ex.executed:
        out.append(f"Executor `{ex.executor}`: **{c['passed']} passed, {c['failed'] + c['error']} failed, "
                   f"{c['skipped']} skipped**" + (f" · [run]({ex.run_url})" if ex.run_url else ""))
    else:
        out.append(f"{len(r.selected)} test(s) selected from the automation repo ({r.framework}). "
                   f"_{ex.note or 'Not executed.'}_")
    if r.selected:
        results = {res.id: res for res in ex.results}
        out.append(f"<details><summary><b>Selected tests</b> ({len(r.selected)})</summary>\n")
        out.append("| Test | Why selected | Result |")
        out.append("|---|---|---|")
        for s in r.selected[:40]:
            res = match_result(s.test.id, results) if results else None
            status = f"{STATUS_ICON.get(res.status, '')} {res.status}" if res else "-"
            out.append(f"| `{s.test.id}` | {'; '.join(s.reasons)} | {status} |")
        if len(r.selected) > 40:
            out.append(f"| _...and {len(r.selected) - 40} more_ | | |")
        out.append("\n</details>")
    failed = [res for res in ex.results if res.status in ("failed", "error")]
    if failed:
        out.append("\n**Failure analysis**")
        out.append(_list([f"`{f.id}` - **{f.classification or 'unknown'}**: {(f.message or '')[:200]}" for f in failed], 10))

    out.append("\n### Test gaps")
    out.append(_list([f"**{g.severity}** · {g.area}: {g.reason}" for g in r.gaps], 10, "_No gaps detected._"))

    if r.ai_notes:
        out.append("\n### AI notes")
        out.append(_list(r.ai_notes, 8))

    status = " · ".join(f"{k}: {v}" for k, v in r.layer_status.items())
    out.append(f"\n<sub>AI Engineering Quality & Impact Platform v{r.version} · {r.generated_at} · "
               f"Intelligence layer - {status}</sub>")
    return "\n".join(out) + "\n"


def gate_status(r: PRQualityReport, review_state: str = "pending") -> tuple[str, str]:
    """Commit status (state, description)."""
    d = r.gate.decision
    state = {Decision.PASS: "success", Decision.REVIEW: review_state, Decision.BLOCK: "failure"}[d]
    desc = f"{d.value}: risk {r.impact.risk_score}/100, {len(r.selected)} tests selected"
    if r.execution.executed:
        c = r.execution.counts
        desc += f", {c['passed']} passed / {c['failed'] + c['error']} failed"
    return state, desc


def gate_conclusion(r: PRQualityReport) -> str:
    return {Decision.PASS: "success", Decision.REVIEW: "neutral", Decision.BLOCK: "failure"}[r.gate.decision]
