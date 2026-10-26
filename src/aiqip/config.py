"""Platform configuration.

Non-secret settings come from an optional YAML file (``aiqip.yaml`` or the path in
``AIQ_CONFIG``). Secrets are only ever read from environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TRUE_VALUES = {"1", "true", "yes", "on"}


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in TRUE_VALUES


@dataclass
class RepoConfig:
    name: str
    branch: str = "master"
    kind: str = "api"
    local_path: str | None = None


@dataclass
class ExecutionConfig:
    # none | github-workflow | command | junit
    executor: str = "none"
    framework: str = "auto"
    workflow_repo: str | None = None
    workflow_file: str = "aiqip-regression.yml"
    workflow_ref: str = "main"
    results_artifact: str = "junit-results"
    command: str | None = None
    working_dir: str | None = None
    junit_glob: str = "**/TEST-*.xml"
    timeout_minutes: int = 90
    poll_seconds: int = 30
    max_tests: int = 200


@dataclass
class GateConfig:
    require_jira_link: bool = True
    block_on_regression_failure: bool = True
    review_on_untested_high_risk: bool = True
    review_if_not_executed: bool = True
    high_risk_score: int = 60
    # status | check
    report_mode: str = "status"
    status_context: str = "AI Quality Gate"
    # Commit status state used for REVIEW (status mode only): pending | success | failure
    review_state: str = "pending"


@dataclass
class DefectsConfig:
    dashboard_id: str | None = "36628"
    extra_jql: list[str] = field(default_factory=list)
    max_results: int = 1000


@dataclass
class DocsConfig:
    sitemaps: list[str] = field(
        default_factory=lambda: [
            "https://documentation.conga.com/en/clm-for-advantage-platform/sitemap.xml",
        ]
    )
    fetch_content: bool = False
    max_pages: int = 400


@dataclass
class Settings:
    github_token: str | None = None
    github_api_url: str = "https://api.github.com"
    jira_base_url: str = "https://conga.atlassian.net"
    jira_email: str | None = None
    jira_api_token: str | None = None
    llm_provider: str = "none"
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_api_version: str | None = None
    post: bool = False
    index_dir: str = ".aiqip/index"
    knowledge_file: str | None = None
    dev_repos: list[RepoConfig] = field(
        default_factory=lambda: [
            RepoConfig("congaengr/ROC-CLM-API", "master", "api"),
            RepoConfig("congaengr/ROC-CLM-UI", "master", "ui"),
        ]
    )
    automation_repo: RepoConfig = field(
        default_factory=lambda: RepoConfig("congaengr/rlpclm-automation", "master", "automation")
    )
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    gate: GateConfig = field(default_factory=GateConfig)
    defects: DefectsConfig = field(default_factory=DefectsConfig)
    docs: DocsConfig = field(default_factory=DocsConfig)

    @property
    def jira_configured(self) -> bool:
        return bool(self.jira_base_url and self.jira_email and self.jira_api_token)

    def redacted(self) -> dict[str, Any]:
        def mask(v: str | None) -> str:
            return "<set>" if v else "<not set>"

        return {
            "github_token": mask(self.github_token),
            "jira_base_url": self.jira_base_url,
            "jira_email": mask(self.jira_email),
            "jira_api_token": mask(self.jira_api_token),
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_api_key": mask(self.llm_api_key),
            "post": self.post,
            "index_dir": self.index_dir,
            "dev_repos": [r.name for r in self.dev_repos],
            "automation_repo": self.automation_repo.name,
            "executor": self.execution.executor,
        }


def _repo(data: dict[str, Any], default_kind: str) -> RepoConfig:
    return RepoConfig(
        name=data["name"],
        branch=data.get("branch", "master"),
        kind=data.get("kind", default_kind),
        local_path=data.get("local_path"),
    )


def _apply(obj: Any, data: dict[str, Any]) -> None:
    for key, value in (data or {}).items():
        if hasattr(obj, key):
            setattr(obj, key, value)


def load_settings(config_path: str | None = None) -> Settings:
    settings = Settings()
    path = config_path or os.environ.get("AIQ_CONFIG")
    if not path and Path("aiqip.yaml").exists():
        path = "aiqip.yaml"
    if path:
        data = yaml.safe_load(Path(path).read_text()) or {}
        if "dev_repos" in data:
            settings.dev_repos = [_repo(r, "api") for r in data["dev_repos"]]
        if "automation_repo" in data:
            settings.automation_repo = _repo(data["automation_repo"], "automation")
        _apply(settings.execution, data.get("execution", {}))
        _apply(settings.gate, data.get("gate", {}))
        _apply(settings.defects, data.get("defects", {}))
        _apply(settings.docs, data.get("docs", {}))
        for key in ("jira_base_url", "github_api_url", "llm_provider", "llm_model", "llm_base_url",
                    "llm_api_version", "index_dir", "knowledge_file"):
            if key in data:
                setattr(settings, key, data[key])

    settings.github_token = _env("AIQ_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")
    settings.github_api_url = _env("GITHUB_API_URL", default=settings.github_api_url) or settings.github_api_url
    settings.jira_base_url = (_env("JIRA_BASE_URL", default=settings.jira_base_url) or "").rstrip("/")
    settings.jira_email = _env("JIRA_EMAIL", "JIRA_USER_EMAIL")
    settings.jira_api_token = _env("JIRA_API_TOKEN")
    settings.llm_provider = _env("AIQ_LLM_PROVIDER", default=settings.llm_provider) or "none"
    settings.llm_model = _env("AIQ_LLM_MODEL", default=settings.llm_model)
    settings.llm_base_url = _env("AIQ_LLM_BASE_URL", default=settings.llm_base_url)
    settings.llm_api_version = _env("AIQ_LLM_API_VERSION", default=settings.llm_api_version)
    settings.llm_api_key = _env("AIQ_LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AZURE_OPENAI_API_KEY")
    settings.post = _env_bool("AIQ_POST", settings.post)
    settings.index_dir = _env("AIQ_INDEX_DIR", default=settings.index_dir) or settings.index_dir
    settings.execution.executor = _env("AIQ_TEST_EXECUTOR", default=settings.execution.executor) or "none"
    return settings
