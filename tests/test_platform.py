import hashlib
import hmac
import json

import httpx
import pytest

from aiqip.config import GateConfig, Settings, load_settings
from aiqip.decision import decide
from aiqip.execution.failure_analysis import classify_failure
from aiqip.execution.junit import match_result, parse_junit_xml
from aiqip.llm import Anthropic, NoLLM, OpenAICompatible, build_llm, parse_json_object
from aiqip.models import Decision, ExecutionSummary, ImpactReport, SelectedTest, TestCase, TestGap, TestResult
from aiqip.server import handle_github_event, handle_jira_event, verify_github_signature


def _sel():
    return [SelectedTest(TestCase("a.B#c", "c", "B.java", "testng"), 5.0, ["area"])]


def test_decision_matrix():
    cfg = GateConfig()
    impact = ImpactReport(risk_score=20)
    ok = ExecutionSummary("junit", True, results=[TestResult("a.B.c", "c", "passed")])
    assert decide(impact, ["X-1"], ["X-1"], _sel(), ok, [], cfg).decision == Decision.PASS

    fail = ExecutionSummary("junit", True, results=[TestResult("a.B.c", "c", "failed", classification="product-regression")])
    assert decide(impact, ["X-1"], ["X-1"], _sel(), fail, [], cfg).decision == Decision.BLOCK

    env = ExecutionSummary("junit", True, results=[TestResult("a.B.c", "c", "failed", classification="environment")])
    assert decide(impact, ["X-1"], ["X-1"], _sel(), env, [], cfg).decision == Decision.REVIEW

    assert decide(impact, [], [], _sel(), ok, [], cfg).decision == Decision.REVIEW
    assert decide(ImpactReport(risk_score=90), ["X-1"], ["X-1"], _sel(), ok, [], cfg).decision == Decision.REVIEW
    gaps = [TestGap("eSignature", "none", "high")]
    assert decide(impact, ["X-1"], ["X-1"], _sel(), ok, gaps, cfg).decision == Decision.REVIEW
    # AI concerns alone never block
    assert decide(impact, ["X-1"], ["X-1"], _sel(), ok, [], cfg, ["looks odd"]).decision == Decision.REVIEW


def test_junit_parsing_and_matching():
    xml = ('<testsuites><testsuite><testcase classname="p.C" name="ok" time="1.5"/>'
           '<testcase classname="p.C" name="bad"><failure message="expected 200 but was 500">trace</failure></testcase>'
           '<testcase classname="p.C" name="skip"><skipped/></testcase></testsuite></testsuites>')
    results = parse_junit_xml(xml)
    assert [r.status for r in results] == ["passed", "failed", "skipped"]
    by_id = {r.id: r for r in results}
    assert match_result("p.C#bad", by_id).status == "failed"
    assert classify_failure(results[1]) == "product-regression"
    assert classify_failure(TestResult("x", "x", "failed", message="Connection refused")) == "environment"
    assert classify_failure(TestResult("x", "x", "failed", message="NoSuchElementException: #save")) == "test-maintenance"


def test_llm_factory_and_json_parsing():
    s = Settings()
    assert isinstance(build_llm(s), NoLLM)
    s.llm_provider, s.llm_api_key = "openai", "k"
    assert isinstance(build_llm(s), OpenAICompatible)
    s.llm_provider = "azure-openai"
    assert build_llm(s).azure
    s.llm_provider = "anthropic"
    assert isinstance(build_llm(s), Anthropic)
    s.llm_provider = "tests.test_platform:CustomLLM"
    assert isinstance(build_llm(s), CustomLLM)
    s.llm_provider = "bogus"
    with pytest.raises(ValueError):
        build_llm(s)
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure: {"a": 2} done') == {"a": 2}
    assert parse_json_object("nope") is None


class CustomLLM(NoLLM):
    def __init__(self, settings):
        self.settings = settings


def test_openai_compatible_request_and_failure_fallback():
    captured = {}

    def ok(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"x": 1}'}}]})

    llm = OpenAICompatible("key", "m", "https://gw.example/v1", transport=httpx.MockTransport(ok))
    assert llm.complete_json("sys", "hi") == {"x": 1}
    assert captured["url"] == "https://gw.example/v1/chat/completions" and captured["auth"] == "Bearer key"
    assert captured["body"]["model"] == "m"

    broken = OpenAICompatible("key", "m", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert broken.complete_json("sys", "hi") is None


def test_settings_secrets_only_from_env(monkeypatch, tmp_path):
    cfg = tmp_path / "aiqip.yaml"
    cfg.write_text("jira_base_url: https://conga.atlassian.net\njira_api_token: SHOULD_BE_IGNORED\n"
                   "gate:\n  high_risk_score: 70\nexecution:\n  executor: command\n")
    monkeypatch.setenv("JIRA_API_TOKEN", "from-env")
    monkeypatch.setenv("AIQ_POST", "false")
    s = load_settings(str(cfg))
    assert s.jira_api_token == "from-env" and s.gate.high_risk_score == 70 and s.execution.executor == "command"
    assert s.post is False
    assert s.redacted()["jira_api_token"] == "<set>"


def test_webhook_helpers():
    body = b'{"a":1}'
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert verify_github_signature("s3cret", body, sig)
    assert not verify_github_signature("s3cret", body, "sha256=bad")
    assert not verify_github_signature(None, body, sig)
    payload = {"action": "synchronize", "pull_request": {"number": 2248, "draft": False},
               "repository": {"full_name": "congaengr/ROC-CLM-API"}}
    assert handle_github_event("pull_request", payload) == ("congaengr/ROC-CLM-API", "pr", 2248)
    assert handle_github_event("pull_request", {**payload, "action": "closed"}) is None
    jira_payload = {"issue": {"key": "CONTRACTS-1", "fields": {"issuetype": {"name": "Bug"}}}}
    assert handle_jira_event(jira_payload, {"bug"}) == "CONTRACTS-1"
    assert handle_jira_event({"issue": {"key": "C-2", "fields": {"issuetype": {"name": "Story"}}}}, {"bug"}) is None
