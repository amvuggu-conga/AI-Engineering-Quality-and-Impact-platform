from __future__ import annotations

import copy
from typing import Any

from aiqip.feedback import publish_bug_report, publish_pr_report
from aiqip.llm import LLMProvider, NoLLM
from aiqip.models import Decision
from aiqip.reporting.adf import adf_to_markdown
from aiqip.workflows.customer_bug import run_bug_analysis
from aiqip.workflows.pr_quality import run_pr_quality

from .conftest import API_REPO


class RecordingGitHub:
    """Wraps the fixture source and records write calls."""

    def __init__(self, inner: Any):
        self.inner = inner
        self.calls: list[tuple[str, tuple]] = []

    def get_pull_request(self, repo, number):
        return self.inner.get_pull_request(repo, number)

    def file_authors(self, repo, path, limit=30):
        return self.inner.file_authors(repo, path, limit)

    def search_code(self, *a, **k):
        return []

    def upsert_pr_comment(self, *args):
        self.calls.append(("comment", args))
        return "https://github.com/x/pull/1#issuecomment-1"

    def create_commit_status(self, *args):
        self.calls.append(("status", args))

    def create_check_run(self, *args, **kwargs):
        self.calls.append(("check", args))
        return "https://github.com/x/runs/1"


def test_pr_quality_blocks_on_regression_failure(settings, layer, fixture_github, fixture_jira):
    report = run_pr_quality(settings, fixture_github, fixture_jira, NoLLM(), API_REPO, 101, layer=layer, execute=True)
    assert report.understanding.jira_keys == ["SYNTH-101"]
    assert report.requirements[0].found and report.requirements[0].alignment in ("aligned", "partial")
    assert {"IRenewalValidator", "RenewalValidator", "RenewalService"} <= set(report.impact.classes)
    assert "RenewalService.RenewAsync" in report.impact.methods
    assert any("/renew" in a for a in report.impact.apis)
    assert any("clm.renewal.preValidation" in f for f in report.impact.feature_flags)
    assert any("IRenewalValidator -> RenewalValidator" in d for d in report.impact.dependencies)
    assert any("UI example-org/clm-ui-sample" in d for d in report.impact.dependents)
    selected = [s.test.id for s in report.selected]
    assert "com.example.clm.api.AgreementRenewalTests#renewUsesDefaultTerm" in selected
    assert "com.example.clm.ui.ClauseLibraryTests#addAlternateClause" not in selected
    assert report.execution.executed and report.execution.counts["failed"] == 1
    assert report.gate.decision == Decision.BLOCK


def test_pr_quality_reviews_when_not_executed(settings, layer, fixture_github, fixture_jira):
    report = run_pr_quality(settings, fixture_github, fixture_jira, NoLLM(), API_REPO, 101, layer=layer, execute=False)
    assert not report.execution.executed
    assert report.gate.decision == Decision.REVIEW
    assert any("not executed" in r for r in report.gate.reasons)


def test_pr_quality_passes_when_clean(settings, layer, fixture_github, fixture_jira, tmp_path):
    results = tmp_path / "TEST-ok.xml"
    results.write_text('<testsuite><testcase classname="com.example.clm.api.AgreementRenewalTests" '
                       'name="renewUsesDefaultTerm"/></testsuite>')
    settings.execution.working_dir = str(tmp_path)
    settings.gate.high_risk_score = 101
    settings.gate.review_on_untested_high_risk = False
    report = run_pr_quality(settings, fixture_github, fixture_jira, NoLLM(), API_REPO, 101, layer=layer, execute=True)
    assert report.gate.decision == Decision.PASS, report.gate.reasons


def test_missing_jira_link_is_review(settings, layer, fixture_github, fixture_jira):
    class NoLinkGitHub(RecordingGitHub):
        def get_pull_request(self, repo, number):
            pr = copy.deepcopy(self.inner.get_pull_request(repo, number))
            pr.body, pr.title, pr.head_ref, pr.commits = "no ticket", "Refactor", "feature/x", []
            return pr

    report = run_pr_quality(settings, NoLinkGitHub(fixture_github), fixture_jira, NoLLM(), API_REPO, 101, layer=layer)
    assert report.gate.decision == Decision.REVIEW
    assert any("No Jira ticket" in r for r in report.gate.reasons)


def test_dry_run_never_writes_and_post_writes(settings, layer, fixture_github, fixture_jira):
    gh = RecordingGitHub(fixture_github)
    report = run_pr_quality(settings, gh, fixture_jira, NoLLM(), API_REPO, 101, layer=layer, execute=True)
    result = publish_pr_report(settings, gh, report)
    assert result["posted"] is False and gh.calls == []
    assert "AI Quality Gate: **BLOCK**" in result["comment"]
    assert result["status"]["state"] == "failure"

    settings.post = True
    result = publish_pr_report(settings, gh, report)
    assert result["posted"] is True
    assert [c[0] for c in gh.calls] == ["comment", "status"]
    settings.gate.report_mode = "check"
    publish_pr_report(settings, gh, report)
    assert gh.calls[-1][0] == "check"


def test_pr_comment_sections(settings, layer, fixture_github, fixture_jira):
    report = run_pr_quality(settings, fixture_github, fixture_jira, NoLLM(), API_REPO, 101, layer=layer, execute=True)
    comment = publish_pr_report(settings, fixture_github, report)["comment"]
    for section in ("### Recommendation", "### Jira traceability", "### Change impact",
                    "### Regression scope & results", "### Test gaps", "SYNTH-101", "❌ failed"):
        assert section in comment


class FakeLLM(LLMProvider):
    name = "fake"

    def __init__(self, answer: str):
        self.answer = answer
        self.prompts: list[str] = []

    def complete(self, system, prompt, max_tokens=1500):
        self.prompts.append(prompt)
        return self.answer


def test_llm_synthesis_is_used_and_concerns_raise_review(settings, layer, fixture_github, fixture_jira, tmp_path):
    (tmp_path / "TEST-ok.xml").write_text('<testsuite><testcase classname="a" name="b"/></testsuite>')
    settings.execution.working_dir = str(tmp_path)
    settings.gate.high_risk_score = 101
    settings.gate.review_on_untested_high_risk = False
    llm = FakeLLM('{"summary": "Adds renewal pre-validation.", "requirements": [{"key": "SYNTH-101", '
                  '"alignment": "partial", "notes": "expired agreements not covered by tests"}], '
                  '"concerns": ["ValidationException is not mapped to HTTP 400"], "test_focus": ["renew expired"]}')
    report = run_pr_quality(settings, fixture_github, fixture_jira, llm, API_REPO, 101, layer=layer, execute=True)
    assert report.ai_used and report.change_summary == "Adds renewal pre-validation."
    assert report.requirements[0].alignment == "partial"
    assert report.gate.decision == Decision.REVIEW
    assert "SYNTH-101" in llm.prompts[0]


def test_bug_analysis_localises_root_cause(settings, layer, fixture_github, fixture_jira):
    report = run_bug_analysis(settings, fixture_jira, fixture_github, NoLLM(), "SYNTH-202", layer=layer)
    assert report.candidates[0].file == "src/Clm.Api/Services/RenewalService.cs"
    assert report.bug.repro_steps[:2] == ["Open an activated agreement", "Click Renew and leave Term (months) empty"]
    assert report.bug.customer_context["Customer Account"] == "Synthetic Customer Inc."
    assert report.bug.customer_context["Severity"] == "Sev 2"
    assert report.owners and report.owners[0][0] == "dev-bob"
    assert any("renewUsesDefaultTerm" in s.test.id for s in report.selected)
    assert report.impact.similar_defects[0].key == "SYNTH-50"

    published = publish_bug_report(settings, fixture_jira, report)
    assert published["posted"] is False
    assert published["adf"]["type"] == "doc"
    md = adf_to_markdown(published["adf"])
    for section in ("Root cause hypothesis", "Code impact", "Regression scope", "Suggested developer to notify"):
        assert section in md


def test_bug_post_skips_when_already_analysed(settings, layer, fixture_github, fixture_jira):
    report = run_bug_analysis(settings, fixture_jira, fixture_github, NoLLM(), "SYNTH-202", layer=layer)

    class Jira:
        posted = False

        def has_analysis_comment(self, key):
            return True

        def add_comment(self, key, adf):
            self.posted = True

    settings.post = True
    jira = Jira()
    result = publish_bug_report(settings, jira, report)
    assert "skipped" in result and not jira.posted
