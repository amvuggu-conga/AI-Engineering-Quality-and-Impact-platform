from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiqip.config import ExecutionConfig, RepoConfig, Settings
from aiqip.connectors.fixtures import FixtureGitHub, FixtureJira
from aiqip.intelligence.code_index import build_code_index
from aiqip.intelligence.defects import build_defect_index
from aiqip.intelligence.layer import IntelligenceLayer, index_file
from aiqip.intelligence.test_index import build_test_index

ROOT = Path(__file__).resolve().parents[1]
SYNTH = ROOT / "examples" / "synthetic"
FIXTURES = SYNTH / "fixtures"
API_REPO = "example-org/clm-api-sample"
UI_REPO = "example-org/clm-ui-sample"
AUTO_REPO = "example-org/clm-automation-sample"


@pytest.fixture()
def index_dir(tmp_path: Path) -> Path:
    d = tmp_path / "index"
    d.mkdir()
    index_file(d, "code", API_REPO).write_text(json.dumps(build_code_index(API_REPO, SYNTH / "api-repo", "api", with_git=False)))
    index_file(d, "code", UI_REPO).write_text(json.dumps(build_code_index(UI_REPO, SYNTH / "ui-repo", "ui", with_git=False)))
    index_file(d, "tests", AUTO_REPO).write_text(json.dumps(build_test_index(AUTO_REPO, SYNTH / "automation-repo")))
    issues = json.loads((FIXTURES / "jira" / "search.json").read_text())["issues"]
    index_file(d, "defects").write_text(json.dumps(build_defect_index(issues, "https://example.atlassian.net", ["x"])))
    return d


@pytest.fixture()
def settings(index_dir: Path) -> Settings:
    s = Settings()
    s.index_dir = str(index_dir)
    s.jira_base_url = "https://example.atlassian.net"
    s.dev_repos = [RepoConfig(API_REPO, kind="api"), RepoConfig(UI_REPO, kind="ui")]
    s.automation_repo = RepoConfig(AUTO_REPO, kind="automation")
    s.execution = ExecutionConfig(executor="junit", working_dir=str(SYNTH / "automation-repo" / "results"),
                                  junit_glob="TEST-*.xml")
    return s


@pytest.fixture()
def layer(settings: Settings) -> IntelligenceLayer:
    return IntelligenceLayer.load(settings.index_dir, [API_REPO, UI_REPO], AUTO_REPO)


@pytest.fixture()
def fixture_github() -> FixtureGitHub:
    return FixtureGitHub(FIXTURES)


@pytest.fixture()
def fixture_jira() -> FixtureJira:
    return FixtureJira(FIXTURES, "https://example.atlassian.net")
