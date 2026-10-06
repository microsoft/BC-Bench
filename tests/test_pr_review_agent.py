import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.pr_review.agent import _prepare_bcquality_root, _resolve_pr_review_root, _write_review_json, run_pr_review_agent
from bcbench.exceptions import AgentError
from bcbench.types import EvaluationCategory, PRReviewMetrics
from tests.conftest import create_codereview_entry


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    out = tmp_path / "out"
    out.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    return out, repo


def _write_output(output_dir: Path, text: str) -> None:
    (output_dir / "al-code-review-findings.json").write_text(text, encoding="utf-8")


def _write_run_manifest(output_dir: Path, *, root_model: str, leaf_model: str) -> None:
    def process(role: str, ordinal: int, skill_id: str, model: str) -> dict:
        metrics = {
            "cli_version": "1.0.83",
            "models": [model],
            "usage_complete": True,
            "malformed_records": 0,
        }
        return {
            "role": role,
            "ordinal": ordinal,
            "skill_id": skill_id,
            "requested_model": model,
            "observed_models": [model],
            "status": "completed",
            "started_at": "2026-09-14T12:00:00Z",
            "completed_at": "2026-09-14T12:00:01Z",
            "duration_seconds": 1.0,
            "exit_code": 0,
            "report_path": f"{role}/{ordinal}/_review-report.json",
            "failure_reason": None,
            "metrics": metrics,
        }

    payload = {
        "schema_version": 1,
        "status": "completed",
        "started_at": "2026-09-14T12:00:00Z",
        "completed_at": "2026-09-14T12:00:02Z",
        "failure_reason": None,
        "engine": {"repository": "microsoft/BC-ALAgents", "commit": "e" * 40, "agent_version": "1.6.6"},
        "bcquality": {"commit": "b" * 40, "source_snapshot": "a" * 64},
        "configuration": {
            "copilot_cli_version": "1.0.83",
            "root_model": root_model,
            "leaf_model": leaf_model,
            "leaf_execution": "serial",
            "max_leaf_concurrency": 4,
            "cli_timeout_minutes": 30,
            "minimum_severity": "Medium",
            "agent_minimum_severity": "Medium",
            "review_source": "local",
        },
        "plan": {"skill_id": "al-code-review", "leaf_count": 1, "leaf_ids": ["al-performance-review"]},
        "processes": [
            process("leaf", 1, "al-performance-review", leaf_model),
            process("root", 2, "al-code-review", root_model),
        ],
    }
    (output_dir / "_run-manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_resolve_pr_review_root_requires_engine_path() -> None:
    with pytest.raises(AgentError, match="Pass --engine-path"):
        _resolve_pr_review_root(None)


def test_prepare_bcquality_root_ignores_ambient_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BCQUALITY_REPO", "contoso/BCQuality")
    monkeypatch.setenv("BCQUALITY_REF", "feature")
    monkeypatch.setenv("BCQUALITY_CONFIG_PATH", "custom.yaml")
    destination = tmp_path / "bcquality"
    destination.mkdir()
    completed = subprocess.CompletedProcess(args=["pwsh"], returncode=0, stdout=f"root={destination}", stderr="")

    with patch("bcbench.agent.pr_review.agent.subprocess.run", return_value=completed) as run:
        root = _prepare_bcquality_root(tmp_path / "engine", "pwsh", destination)

    assert root == destination
    child_env = run.call_args.kwargs["env"]
    assert not any(name.startswith("BCQUALITY_") for name in child_env)


def test_valid_empty_findings_is_a_clean_review(tmp_path: Path) -> None:
    out, repo = _dirs(tmp_path)
    _write_output(out, json.dumps({"outcome": "completed", "outcome-reason": "", "findings": []}))
    assert _write_review_json(out, repo) == 0
    assert json.loads((repo / "review.json").read_text(encoding="utf-8")) == []


def test_findings_are_mapped(tmp_path: Path) -> None:
    out, repo = _dirs(tmp_path)
    report = {
        "outcome": "completed",
        "findings": [{"severity": "High", "filePath": "src/Foo.al", "lineNumber": 42, "issue": "x", "domain": "ui"}],
    }
    _write_output(out, json.dumps(report))
    assert _write_review_json(out, repo) == 1


def test_missing_agent_output_raises(tmp_path: Path) -> None:
    out, repo = _dirs(tmp_path)
    with pytest.raises(AgentError, match="did not produce"):
        _write_review_json(out, repo)


@pytest.mark.parametrize("text", ["", "   ", "not json", "[]"])
def test_invalid_output_raises_instead_of_clean_review(tmp_path: Path, text: str) -> None:
    out, repo = _dirs(tmp_path)
    _write_output(out, text)
    with pytest.raises(AgentError, match="empty or invalid"):
        _write_review_json(out, repo)
    assert not (repo / "review.json").exists()


@pytest.mark.parametrize(
    "report",
    [
        {"outcome": "completed"},
        {"outcome": "partial", "findings": None},
        {"outcome": "no-knowledge", "findings": "nope"},
    ],
)
def test_malformed_report_raises_instead_of_clean_review(tmp_path: Path, report: dict) -> None:
    out, repo = _dirs(tmp_path)
    _write_output(out, json.dumps(report))
    with pytest.raises(AgentError, match="no findings list"):
        _write_review_json(out, repo)
    assert not (repo / "review.json").exists()


def test_failed_engine_outcome_raises_instead_of_clean_review(tmp_path: Path) -> None:
    out, repo = _dirs(tmp_path)
    _write_output(out, json.dumps({"outcome": "failed", "outcomeReason": "dispatch failed", "findings": []}))

    with pytest.raises(AgentError, match="dispatch failed"):
        _write_review_json(out, repo)

    assert not (repo / "review.json").exists()


def test_not_applicable_engine_outcome_raises_instead_of_clean_review(tmp_path: Path) -> None:
    out, repo = _dirs(tmp_path)
    _write_output(out, json.dumps({"outcome": "not-applicable", "outcome-reason": "No AL files.", "findings": []}))

    with pytest.raises(AgentError, match="must contain AL changes"):
        _write_review_json(out, repo)

    assert not (repo / "review.json").exists()


def test_engine_environment_uses_target_repository_and_absolute_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "microsoft/BC-Bench")
    monkeypatch.setenv("BCQUALITY_REF", "ambient-override")
    monkeypatch.setenv("COPILOT_REVIEW_LEAF_MODEL", "gpt-5.4")
    monkeypatch.setenv("COPILOT_REVIEW_LEAF_EXECUTION", "serial")
    monkeypatch.setenv("COPILOT_REVIEW_MAX_LEAF_CONCURRENCY", "4")
    settings = {"min_severity": "Medium"}
    completed = subprocess.CompletedProcess(args=["pwsh"], returncode=0, stdout="✓", stderr="")
    entry = create_codereview_entry(repo="microsoft/BCApps")
    bcquality_root = tmp_path / "bcquality"
    knowledge_root = bcquality_root / "microsoft" / "knowledge" / "performance"
    knowledge_root.mkdir(parents=True)
    (knowledge_root / "one.md").write_text("# One", encoding="utf-8")
    (bcquality_root / "_filter-report.json").write_text('{"removed": []}', encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "_run-metrics.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "metrics_source": "copilot-cli-otel",
                "cli_version": "1.0.83",
                "wall_time_seconds": 2.4,
                "prompt_tokens": 100,
                "cached_tokens": 20,
                "cache_creation_tokens": 5,
                "completion_tokens": 10,
                "reasoning_tokens": 4,
                "total_tokens": 110,
                "api_calls": 2,
                "failed_api_calls": 0,
                "usage_api_calls": 2,
                "ai_credits": 0.25,
                "premium_requests": 0.5,
                "models": ["gpt-5.4", "gpt-5.6-luna"],
                "usage_complete": True,
                "malformed_records": 0,
            }
        ),
        encoding="utf-8",
    )
    _write_run_manifest(output_dir, root_model="gpt-5.6-luna", leaf_model="gpt-5.4")

    with (
        patch("bcbench.agent.pr_review.agent._load_pr_review_settings", return_value=settings),
        patch("bcbench.agent.pr_review.agent._resolve_pr_review_root", return_value=tmp_path / "engine") as resolve_engine,
        patch("bcbench.agent.pr_review.agent._resolve_pwsh", return_value="pwsh"),
        patch("bcbench.agent.pr_review.agent._commit_patch_as_head"),
        patch("bcbench.agent.pr_review.agent._init_trusted_workspace", return_value=tmp_path / "trusted"),
        patch("bcbench.agent.pr_review.agent._prepare_bcquality_root", return_value=bcquality_root) as prepare_bcquality,
        patch("bcbench.agent.pr_review.agent._write_review_json", return_value=0),
        patch("bcbench.agent.pr_review.agent.time.monotonic", side_effect=[10.0, 12.5]),
        patch("bcbench.agent.pr_review.agent.subprocess.run", return_value=completed) as run_process,
    ):
        metrics, config = run_pr_review_agent(
            entry=entry,
            model="gpt-5.6-luna",
            category=EvaluationCategory.CODE_REVIEW,
            repo_path=tmp_path / "repo",
            output_dir=Path("output"),
            agent_version="e" * 40,
            engine_path=tmp_path / "engine",
        )

    assert isinstance(metrics, PRReviewMetrics)
    assert metrics.execution_time == 2.5
    assert metrics.prompt_tokens == 100
    assert metrics.completion_tokens == 10
    assert metrics.total_tokens == 110
    assert metrics.ai_credits == 0.25
    assert metrics.api_calls == 2
    assert metrics.copilot_cli_version == "1.0.83"
    assert metrics.leaf_model == "gpt-5.4"
    assert metrics.leaf_execution == "serial"
    assert metrics.max_leaf_concurrency == 4
    assert metrics.bcquality_commit == "b" * 40
    assert metrics.review_process_count == 2
    assert config.is_empty()
    resolve_engine.assert_called_once_with(tmp_path / "engine")
    prepare_bcquality.assert_called_once_with(tmp_path / "engine", "pwsh", (tmp_path / "output" / "bcquality").resolve())
    assert run_process.call_args.kwargs["encoding"] == "utf-8"
    assert run_process.call_args.kwargs["cwd"] == str((tmp_path / "repo").resolve())
    engine_env = run_process.call_args.kwargs["env"]
    assert engine_env["REVIEW_TARGET_WORKSPACE"] == str((tmp_path / "repo").resolve())
    assert engine_env["REVIEW_OUTPUT_DIR"] == str((tmp_path / "output").resolve())
    assert engine_env["REVIEW_WORKSPACE"] == str(tmp_path / "trusted")
    assert engine_env["BCQUALITY_ROOT"] == str(tmp_path / "bcquality")
    assert "BCQUALITY_SHA" not in engine_env
    assert "BCQUALITY_REF" not in engine_env
    assert engine_env["GITHUB_REPOSITORY"] == "microsoft/BCApps"
    assert engine_env["AGENT_MINIMUM_SEVERITY"] == "Medium"
    assert engine_env["COPILOT_REVIEW_CLI_VERSION"] == "1.0.83"
    assert engine_env["COPILOT_REVIEW_LEAF_MODEL"] == "gpt-5.4"
    assert engine_env["COPILOT_REVIEW_LEAF_EXECUTION"] == "serial"
    assert run_process.call_args.args[0][-1].endswith("Invoke-CopilotPRReview.ps1")
    assert "-GenerateOnly" not in run_process.call_args.args[0]
