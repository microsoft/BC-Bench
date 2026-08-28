import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.pr_review.agent import _prepare_bcquality_root, _prepare_pr_review_root, _write_review_json, run_pr_review_agent
from bcbench.exceptions import AgentError
from bcbench.types import EvaluationCategory
from tests.conftest import create_codereview_entry


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    out = tmp_path / "out"
    out.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    return out, repo


def _write_output(output_dir: Path, text: str) -> None:
    (output_dir / "al-code-review-findings.json").write_text(text, encoding="utf-8")


def test_prepare_pr_review_root_uses_local_checkout(tmp_path: Path) -> None:
    with patch("bcbench.agent.pr_review.agent._resolve_pr_review_root", return_value=tmp_path) as resolve:
        root = _prepare_pr_review_root("ignored/repo", "ignored-ref", tmp_path, tmp_path / "clone")

    assert root == tmp_path
    resolve.assert_called_once_with(tmp_path)


def test_prepare_pr_review_root_clones_configured_revision(tmp_path: Path) -> None:
    destination = tmp_path / "clone"
    with (
        patch("bcbench.agent.pr_review.agent.clone_repo_at_revision") as clone,
        patch("bcbench.agent.pr_review.agent._resolve_pr_review_root", return_value=destination),
    ):
        root = _prepare_pr_review_root("microsoft/BC-ALAgents", "a" * 40, None, destination)

    assert root == destination
    clone.assert_called_once_with("microsoft/BC-ALAgents", "a" * 40, destination)


def test_prepare_pr_review_root_requires_configured_source(tmp_path: Path) -> None:
    with pytest.raises(AgentError, match="repo and ref must be configured"):
        _prepare_pr_review_root(None, None, None, tmp_path / "clone")


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
    settings = {
        "min_severity": "Medium",
        "engine": {"repo": "microsoft/BC-ALAgents", "ref": "a" * 40},
    }
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
                "cli_version": "1.0.81-0",
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
                "models": ["gpt-5.6-luna"],
                "usage_complete": True,
                "malformed_records": 0,
            }
        ),
        encoding="utf-8",
    )

    with (
        patch("bcbench.agent.pr_review.agent._load_pr_review_settings", return_value=settings),
        patch("bcbench.agent.pr_review.agent._prepare_pr_review_root", return_value=tmp_path / "engine") as prepare_engine,
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
            engine_local_path=tmp_path / "engine",
        )

    assert metrics is not None
    assert metrics.execution_time == 2.5
    assert metrics.prompt_tokens == 100
    assert metrics.completion_tokens == 10
    assert metrics.total_tokens == 110
    assert metrics.ai_credits == 0.25
    assert config.is_empty()
    prepare_engine.assert_called_once_with("microsoft/BC-ALAgents", "a" * 40, tmp_path / "engine", (tmp_path / "output" / "bc-alagents").resolve())
    prepare_bcquality.assert_called_once_with(tmp_path / "engine", "pwsh", (tmp_path / "output" / "bcquality").resolve())
    assert run_process.call_args.kwargs["encoding"] == "utf-8"
    assert run_process.call_args.kwargs["cwd"] == str((tmp_path / "repo").resolve())
    engine_env = run_process.call_args.kwargs["env"]
    assert engine_env["REVIEW_TARGET_WORKSPACE"] == str((tmp_path / "repo").resolve())
    assert engine_env["REVIEW_OUTPUT_DIR"] == str((tmp_path / "output").resolve())
    assert engine_env["REVIEW_WORKSPACE"] == str(tmp_path / "trusted")
    assert engine_env["BCQUALITY_ROOT"] == str(tmp_path / "bcquality")
    assert "BCQUALITY_REF" not in engine_env
    assert engine_env["GITHUB_REPOSITORY"] == "microsoft/BCApps"
    assert engine_env["AGENT_MINIMUM_SEVERITY"] == "Medium"
    assert run_process.call_args.args[0][-1].endswith("Invoke-CopilotPRReview.ps1")
    assert "-GenerateOnly" not in run_process.call_args.args[0]
