"""AI Quality Decision: evidence-based PASS / REVIEW / BLOCK.

The gate is deterministic and explainable: every reason cites evidence gathered by the
pipeline. The LLM can add review concerns (e.g. requirement mismatch) which can raise
PASS to REVIEW but can never on its own produce BLOCK.
"""

from __future__ import annotations

from .config import GateConfig
from .models import Decision, ExecutionSummary, GateResult, ImpactReport, SelectedTest, TestGap


def decide(impact: ImpactReport, jira_keys: list[str], jira_found: list[str], selected: list[SelectedTest],
           execution: ExecutionSummary, gaps: list[TestGap], cfg: GateConfig,
           ai_concerns: list[str] | None = None) -> GateResult:
    block: list[str] = []
    review: list[str] = []
    evidence: list[str] = []

    failed = [r for r in execution.results if r.status in ("failed", "error")]
    regressions = [r for r in failed if r.classification in ("product-regression", None, "unknown")]
    other_failures = [r for r in failed if r not in regressions]
    counts = execution.counts

    if execution.executed:
        evidence.append(f"Executed {len(execution.results)} regression test(s): {counts['passed']} passed, "
                        f"{counts['failed'] + counts['error']} failed, {counts['skipped']} skipped.")
    if regressions and cfg.block_on_regression_failure:
        block.append(f"{len(regressions)} regression test failure(s) classified as product regression or "
                     f"unexplained (e.g. {regressions[0].id}).")
    if other_failures:
        review.append(f"{len(other_failures)} failure(s) attributed to environment/test maintenance/data - "
                      "re-run or confirm.")

    if not jira_keys:
        (review if cfg.require_jira_link else evidence).append("No Jira ticket linked in PR title/body/branch/commits.")
    else:
        missing = [k for k in jira_keys if k not in jira_found]
        evidence.append(f"Linked Jira: {', '.join(jira_keys)}.")
        if missing:
            review.append(f"Linked Jira issue(s) could not be read for traceability: {', '.join(missing)}.")

    if not selected:
        review.append("No regression tests could be selected for the impacted areas.")
    elif not execution.executed and cfg.review_if_not_executed:
        review.append(f"{len(selected)} regression test(s) selected but not executed ({execution.note or 'plan only'}).")

    high_gaps = [g for g in gaps if g.severity == "high"]
    if high_gaps and cfg.review_on_untested_high_risk:
        review.append(f"{len(high_gaps)} high-severity test gap(s): " + "; ".join(g.area for g in high_gaps[:3]) + ".")

    if impact.risk_score >= cfg.high_risk_score:
        review.append(f"High change risk score {impact.risk_score}/100 ({', '.join(impact.risk_factors[:3])}).")
    evidence.append(f"Risk score {impact.risk_score}/100.")

    for concern in ai_concerns or []:
        review.append(f"AI review: {concern}")

    if block:
        return GateResult(Decision.BLOCK, block + review, evidence)
    if review:
        return GateResult(Decision.REVIEW, review, evidence)
    return GateResult(Decision.PASS, ["Linked requirement traced, impacted regression scope executed and passed, "
                                      "no high-severity gaps."], evidence)
