"""Render the customer-bug analysis as a Jira Cloud comment (ADF)."""

from __future__ import annotations

from typing import Any

from ..connectors.jira import ANALYSIS_MARKER
from ..taxonomy import area_name
from ..workflows.customer_bug import BugAnalysisReport
from .adf import ADFDocument, text


def render_jira_comment(r: BugAnalysisReport) -> dict[str, Any]:
    doc = ADFDocument()
    doc.heading(f"{ANALYSIS_MARKER} - first AI analysis", 3)
    doc.panel("info", "Automated first-pass analysis. Treat as a hypothesis to verify; it does not replace "
                      "engineering triage.")

    doc.heading("Bug understanding", 4)
    doc.paragraph(text("Business behavior: ", bold=True), r.bug.business_behavior[:600] or r.bug.issue.summary)
    if r.bug.repro_steps:
        doc.paragraph(text("Reproduction steps (as reported):", bold=True))
        doc.bullets(r.bug.repro_steps[:10])
    if r.bug.customer_context:
        doc.paragraph(text("Customer context:", bold=True))
        doc.bullets([f"{k}: {v[:200]}" for k, v in list(r.bug.customer_context.items())[:8]])
    if r.bug.areas:
        doc.paragraph(text("Functional areas: ", bold=True), ", ".join(area_name(a) for a, _ in r.bug.areas))

    doc.heading("Root cause hypothesis", 4)
    doc.paragraph(r.hypothesis)
    doc.paragraph(text("Confidence: ", bold=True), r.confidence)

    doc.heading("Code impact", 4)
    if r.candidates:
        doc.bullets([[text(c.file, code=True), f" ({c.repo}) - " + "; ".join(c.reasons[:3])] for c in r.candidates[:6]])
    else:
        doc.paragraph("No code candidates (dev repos not indexed or no match).")
    if r.impact.apis:
        doc.paragraph(text("APIs: ", bold=True), ", ".join(r.impact.apis[:6]))
    if r.impact.dependents:
        doc.paragraph(text("Dependents: ", bold=True), ", ".join(r.impact.dependents[:6]))

    doc.heading("Regression scope", 4)
    if r.selected:
        doc.bullets([[text(s.test.id, code=True), " - " + "; ".join(s.reasons[:2])] for s in r.selected[:12]])
        if len(r.selected) > 12:
            doc.paragraph(f"...and {len(r.selected) - 12} more tests.")
    else:
        doc.paragraph("No automation tests mapped (automation repo not indexed or no match).")
    if r.gaps:
        doc.paragraph(text("Test gaps: ", bold=True), "; ".join(f"{g.area} ({g.severity})" for g in r.gaps[:5]))

    if r.impact.similar_defects:
        doc.heading("Related historical defects", 4)
        doc.bullets([[(s.key, s.url or ""), f" {s.summary} ({s.status or 'n/a'})"] for s in r.impact.similar_defects[:5]])
    if r.impact.docs:
        doc.heading("Product documentation", 4)
        doc.bullets([[(d.title, d.url)] for d in r.impact.docs[:3]])

    doc.heading("Suggested developer to notify", 4)
    if r.owners:
        doc.bullets([f"{who} (recent ownership of the top candidate files)" for who, _ in r.owners])
    else:
        doc.paragraph("No ownership data (needs git history in the code index or GitHub access).")

    doc.heading("Next steps", 4)
    doc.bullets(r.next_steps)
    doc.rule()
    doc.paragraph(text(f"Generated {r.generated_at} by AI Engineering Quality & Impact Platform v{r.version}"
                       f"{' (LLM-assisted)' if r.ai_used else ' (deterministic, no LLM)'}.", code=False))
    return doc.to_dict()
