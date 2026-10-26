"""Test executors. Triggering execution is a side effect, so it only happens when the caller
passes ``execute=True`` (CLI ``--execute`` / ``AIQ_EXECUTE=true``)."""

from __future__ import annotations

import datetime as dt
import logging
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from ..analysis.test_selection import build_filter
from ..config import ExecutionConfig
from ..models import ExecutionSummary, SelectedTest, TestResult
from .junit import match_result, parse_junit_glob, parse_junit_xml

log = logging.getLogger(__name__)


def _attach(selected: list[SelectedTest], results: list[TestResult]) -> list[TestResult]:
    """Keep results for the selected tests (by id), falling back to everything that ran."""
    by_id = {r.id: r for r in results}
    matched = [m for s in selected if (m := match_result(s.test.id, by_id))]
    return matched or results


def run_tests(selected: list[SelectedTest], cfg: ExecutionConfig, framework: str, execute: bool,
              github: Any | None = None, correlation: str = "") -> ExecutionSummary:
    executor = cfg.executor
    if not selected:
        return ExecutionSummary(executor, False, note="No regression tests selected.")
    if executor == "none":
        return ExecutionSummary(executor, False, note="Plan only: no test executor configured (AIQ_TEST_EXECUTOR).")
    if not execute:
        return ExecutionSummary(executor, False, note=f"Plan only: executor '{executor}' is configured but execution "
                                                      "was not requested (use --execute).")
    fw = cfg.framework if cfg.framework != "auto" else framework
    test_filter = build_filter(selected, fw)
    try:
        if executor == "junit":
            results = parse_junit_glob(cfg.working_dir or ".", cfg.junit_glob)
            return ExecutionSummary(executor, bool(results), results=_attach(selected, results),
                                    note=None if results else f"No JUnit files matched {cfg.junit_glob}")
        if executor == "command":
            return _run_command(selected, cfg, test_filter)
        if executor == "github-workflow":
            return _run_github_workflow(selected, cfg, test_filter, fw, github, correlation)
    except Exception as exc:  # execution failures are reported, not raised
        log.exception("Test execution failed")
        return ExecutionSummary(executor, False, note=f"Execution error: {exc}")
    return ExecutionSummary(executor, False, note=f"Unknown executor '{executor}'")


def _run_command(selected: list[SelectedTest], cfg: ExecutionConfig, test_filter: str) -> ExecutionSummary:
    if not cfg.command:
        return ExecutionSummary("command", False, note="execution.command is not configured")
    workdir = Path(cfg.working_dir or ".")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write("\n".join(s.test.id for s in selected))
        tests_file = fh.name
    cmd = cfg.command.format(filter=shlex.quote(test_filter), tests_file=tests_file)
    started = dt.datetime.now().timestamp()
    proc = subprocess.run(cmd, shell=True, cwd=workdir, capture_output=True, text=True,
                          timeout=cfg.timeout_minutes * 60)
    fresh = [p for p in workdir.glob(cfg.junit_glob) if p.stat().st_mtime >= started - 1]
    results: list[TestResult] = []
    for p in fresh:
        results.extend(parse_junit_xml(p.read_bytes()))
    note = None if results else f"Command exited {proc.returncode} without JUnit output: {proc.stderr[-500:]}"
    return ExecutionSummary("command", bool(results), results=_attach(selected, results), note=note)


def _run_github_workflow(selected: list[SelectedTest], cfg: ExecutionConfig, test_filter: str, framework: str,
                         github: Any, correlation: str) -> ExecutionSummary:
    if github is None or not cfg.workflow_repo:
        return ExecutionSummary("github-workflow", False, note="execution.workflow_repo / GitHub client not configured")
    corr = f"aiqip-{correlation}-{uuid.uuid4().hex[:8]}"
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    github.dispatch_workflow(cfg.workflow_repo, cfg.workflow_file, cfg.workflow_ref,
                             {"tests": test_filter[:60000], "framework": framework, "correlation_id": corr})
    run = github.find_workflow_run(cfg.workflow_repo, cfg.workflow_file, corr, since)
    if not run:
        return ExecutionSummary("github-workflow", False, note=f"Dispatched, but no run with correlation id {corr} "
                                "appeared. The workflow must set `run-name` to include inputs.correlation_id.")
    run = github.wait_for_run(cfg.workflow_repo, run["id"], cfg.timeout_minutes * 60, cfg.poll_seconds)
    url = run.get("html_url")
    if run.get("status") != "completed":
        return ExecutionSummary("github-workflow", False, run_url=url, note="Timed out waiting for the regression run")
    files = github.download_artifact_files(cfg.workflow_repo, run["id"], cfg.results_artifact)
    results: list[TestResult] = []
    for name, content in files.items():
        if name.endswith(".xml"):
            results.extend(parse_junit_xml(content))
    note = None if results else f"Run {run.get('conclusion')} but artifact '{cfg.results_artifact}' had no JUnit XML"
    return ExecutionSummary("github-workflow", bool(results), run_url=url, results=_attach(selected, results), note=note)
