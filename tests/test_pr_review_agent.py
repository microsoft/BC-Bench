import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.pr_review.agent import _write_review_json, run_pr_review_agent
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


def test_engine_environment_uses_target_repository_and_absolute_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "microsoft/BC-Bench")
    settings = {
        "min_severity": "Medium",
        "bcquality": {"repo": None, "ref": None},
    }
    completed = subprocess.CompletedProcess(args=["pwsh"], returncode=0, stdout="✓", stderr="")
    entry = create_codereview_entry(repo="microsoft/BCApps")
    bcquality_root = tmp_path / "bcquality"
    knowledge_root = bcquality_root / "microsoft" / "knowledge" / "performance"
    knowledge_root.mkdir(parents=True)
    (knowledge_root / "one.md").write_text("# One", encoding="utf-8")
    (bcquality_root / "_filter-report.json").write_text('{"removed": []}', encoding="utf-8")

    with (
        patch("bcbench.agent.pr_review.agent._load_pr_review_settings", return_value=settings),
        patch("bcbench.agent.pr_review.agent._resolve_pr_review_root", return_value=tmp_path / "engine"),
        patch("bcbench.agent.pr_review.agent._resolve_pwsh", return_value="pwsh"),
        patch("bcbench.agent.pr_review.agent._commit_patch_as_head"),
        patch("bcbench.agent.pr_review.agent._init_trusted_workspace", return_value=tmp_path / "trusted"),
        patch("bcbench.agent.pr_review.agent._prepare_bcquality_root", return_value=bcquality_root),
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
            engine_path=tmp_path / "engine",
        )

    assert metrics is not None
    assert metrics.execution_time == 2.5
    assert metrics.knowledge_files == 1
    assert metrics.knowledge_pruned == 0
    assert config.is_empty()
    assert run_process.call_args.kwargs["encoding"] == "utf-8"
    assert run_process.call_args.kwargs["cwd"] == str((tmp_path / "repo").resolve())
    engine_env = run_process.call_args.kwargs["env"]
    assert engine_env["REVIEW_TARGET_WORKSPACE"] == str((tmp_path / "repo").resolve())
    assert engine_env["REVIEW_OUTPUT_DIR"] == str((tmp_path / "output").resolve())
    assert engine_env["REVIEW_WORKSPACE"] == str(tmp_path / "trusted")
    assert engine_env["BCQUALITY_ROOT"] == str(tmp_path / "bcquality")
    assert engine_env["GITHUB_REPOSITORY"] == "microsoft/BCApps"
    assert engine_env["AGENT_MINIMUM_SEVERITY"] == "Medium"
    assert run_process.call_args.args[0][-1].endswith("Invoke-CopilotPRReview.ps1")
    assert "-GenerateOnly" not in run_process.call_args.args[0]
