import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.pr_review.agent import _bcquality_content_digest, _build_experiment_configuration, _read_pr_review_metrics, _write_review_json, run_pr_review_agent
from bcbench.exceptions import AgentError
from bcbench.types import EvaluationCategory, ExperimentConfiguration
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


def test_copilot_metrics_are_read_from_engine_transcript(tmp_path: Path) -> None:
    transcript = "err: AI Credits 2 (1m 5s)\nerr: Tokens ↑ 125.5k (100k cached) • ↓ 3.6k\n"
    (tmp_path / "agent-transcript.log").write_text(transcript, encoding="utf-8")

    metrics = _read_pr_review_metrics(tmp_path, execution_time=70.0)

    assert metrics.execution_time == 70.0
    assert metrics.prompt_tokens == 125500
    assert metrics.completion_tokens == 3600
    assert metrics.ai_credits == 2.0


def test_missing_engine_transcript_keeps_execution_time(tmp_path: Path) -> None:
    metrics = _read_pr_review_metrics(tmp_path, execution_time=12.5)

    assert metrics.execution_time == 12.5
    assert metrics.prompt_tokens is None


def test_engine_output_is_decoded_as_utf8_and_paths_are_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = {
        "path": str(tmp_path / "engine"),
        "min_severity": "Low",
        "bcquality": {"repo": None, "ref": None, "local_path": None},
    }
    completed = subprocess.CompletedProcess(args=["pwsh"], returncode=0, stdout="✓", stderr="")

    with (
        patch("bcbench.agent.pr_review.agent._load_pr_review_settings", return_value=settings),
        patch("bcbench.agent.pr_review.agent._resolve_pr_review_root", return_value=tmp_path / "engine"),
        patch("bcbench.agent.pr_review.agent._resolve_pwsh", return_value="pwsh"),
        patch("bcbench.agent.pr_review.agent._commit_patch_as_head"),
        patch("bcbench.agent.pr_review.agent._init_trusted_workspace", return_value=tmp_path / "trusted"),
        patch("bcbench.agent.pr_review.agent._prepare_bcquality_root", return_value=(tmp_path / "bcquality", None)),
        patch("bcbench.agent.pr_review.agent._build_experiment_configuration", return_value=ExperimentConfiguration()),
        patch("bcbench.agent.pr_review.agent._write_review_json", return_value=0),
        patch("bcbench.agent.pr_review.agent.subprocess.run", return_value=completed) as run_process,
    ):
        run_pr_review_agent(
            entry=create_codereview_entry(),
            model="gpt-5.6-luna",
            category=EvaluationCategory.CODE_REVIEW,
            repo_path=tmp_path / "repo",
            output_dir=Path("output"),
        )

    assert run_process.call_args.kwargs["encoding"] == "utf-8"
    assert run_process.call_args.kwargs["cwd"] == str((tmp_path / "repo").resolve())
    assert run_process.call_args.kwargs["env"]["REVIEW_TARGET_WORKSPACE"] == str((tmp_path / "repo").resolve())
    assert run_process.call_args.kwargs["env"]["REVIEW_OUTPUT_DIR"] == str((tmp_path / "output").resolve())
    assert run_process.call_args.kwargs["env"]["REVIEW_WORKSPACE"] == str(tmp_path / "trusted")
    assert run_process.call_args.kwargs["env"]["BCQUALITY_ROOT"] == str(tmp_path / "bcquality")
    assert run_process.call_args.args[0][-1].endswith("Invoke-CopilotPRReview.ps1")
    assert "-GenerateOnly" not in run_process.call_args.args[0]


def test_bcquality_content_digest_ignores_run_artifacts(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "entry.md").write_text("content", encoding="utf-8")
    original = _bcquality_content_digest(tmp_path)

    (tmp_path / "_filter-report.json").write_text("machine-specific", encoding="utf-8")
    (tmp_path / "_review-report.json").write_text("stale", encoding="utf-8")
    assert _bcquality_content_digest(tmp_path) == original

    (tmp_path / "skills" / "entry.md").write_text("changed", encoding="utf-8")
    assert _bcquality_content_digest(tmp_path) != original


def test_experiment_configuration_records_exact_provenance(tmp_path: Path) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=engine, check=True)
    (engine / "engine.ps1").write_text("engine", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=engine, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-q", "-m", "engine"],
        cwd=engine,
        check=True,
    )
    bcquality = tmp_path / "bcquality"
    bcquality.mkdir()
    (bcquality / "entry.md").write_text("knowledge", encoding="utf-8")

    config = _build_experiment_configuration(engine, bcquality, "abc123", custom_bcquality=False)

    assert config.is_empty()
    assert config.knowledge_base is None
    assert config.provenance is not None
    assert config.provenance.agent_harness is not None
    assert config.provenance.agent_harness.startswith("BC-ALAgents@")
    assert config.provenance.knowledge_base == f"BCQuality@abc123+content.{_bcquality_content_digest(bcquality)}"
