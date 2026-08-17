import re
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from bcbench.cli import app
from bcbench.commands import evaluate as evaluate_commands
from bcbench.commands import run as run_commands
from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.types import AgentHarness, EvaluationCategory


@pytest.mark.parametrize(
    ("command", "runner_name"),
    [
        (run_commands.run_copilot, "run_copilot_agent"),
        (run_commands.run_claude, "run_claude_code"),
    ],
)
def test_generic_run_commands_accept_code_review(tmp_path: Path, command, runner_name: str) -> None:
    entry = object()
    with (
        patch.object(CodeReviewEntry, "load", return_value=[entry]),
        patch.object(CodeReviewPipeline, "setup_workspace"),
        patch.object(run_commands, runner_name) as agent_runner,
    ):
        command("synthetic__style-018", EvaluationCategory.CODE_REVIEW, repo_path=tmp_path, output_dir=tmp_path / "out")

    assert agent_runner.call_args.kwargs["entry"] is entry
    assert agent_runner.call_args.kwargs["category"] is EvaluationCategory.CODE_REVIEW


@pytest.mark.parametrize(
    ("command", "agent_name"),
    [
        (evaluate_commands.evaluate_copilot, AgentHarness.COPILOT),
        (evaluate_commands.evaluate_claude_code, AgentHarness.CLAUDE),
    ],
)
def test_generic_evaluate_commands_use_code_review_pipeline(tmp_path: Path, command, agent_name: AgentHarness) -> None:
    contexts = []
    with (
        patch.object(CodeReviewEntry, "load", return_value=[object()]),
        patch.object(CodeReviewPipeline, "execute", side_effect=lambda context, runner: contexts.append(context)),
    ):
        command(
            "synthetic__style-018",
            EvaluationCategory.CODE_REVIEW,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
            run_id=agent_name.name.lower(),
        )

    assert len(contexts) == 1
    assert contexts[0].agent_name is agent_name
    assert contexts[0].category is EvaluationCategory.CODE_REVIEW


def test_pr_review_evaluation_is_fixed_to_runner_and_category(tmp_path: Path) -> None:
    contexts = []
    with (
        patch.object(CodeReviewEntry, "load", return_value=[object()]),
        patch.object(CodeReviewPipeline, "execute", side_effect=lambda context, runner: contexts.append(context)),
    ):
        evaluate_commands._run_pr_review_evaluation(
            "synthetic__style-018",
            model="gpt-5.6-luna",
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
            run_id="pr-review",
        )

    assert len(contexts) == 1
    assert contexts[0].agent_name is AgentHarness.PR_REVIEW
    assert contexts[0].category is EvaluationCategory.CODE_REVIEW


def test_pr_review_run_is_fixed_to_code_review(tmp_path: Path) -> None:
    entry = object()
    with (
        patch.object(CodeReviewEntry, "load", return_value=[entry]),
        patch.object(CodeReviewPipeline, "setup_workspace"),
        patch.object(run_commands, "run_pr_review_agent") as agent_runner,
    ):
        run_commands._run_pr_review(
            "synthetic__style-018",
            model="gpt-5.6-luna",
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
        )

    assert agent_runner.call_args.kwargs["entry"] is entry
    assert agent_runner.call_args.kwargs["category"] is EvaluationCategory.CODE_REVIEW


def test_pr_review_is_public_command_and_code_review_alias_is_hidden() -> None:
    runner = CliRunner()

    run_help = runner.invoke(app, ["run", "--help"])
    evaluate_help = runner.invoke(app, ["evaluate", "--help"])

    assert run_help.exit_code == 0
    assert evaluate_help.exit_code == 0
    assert "pr-review" in run_help.stdout
    assert "pr-review" in evaluate_help.stdout
    assert re.search(r"^\s*│\s+code-review\s", run_help.stdout, re.MULTILINE) is None
    assert re.search(r"^\s*│\s+code-review\s", evaluate_help.stdout, re.MULTILINE) is None


def test_hidden_code_review_aliases_remain_compatible(tmp_path: Path) -> None:
    runner = CliRunner()
    with (
        patch.object(CodeReviewEntry, "load", return_value=[object()]),
        patch.object(CodeReviewPipeline, "setup_workspace"),
        patch.object(CodeReviewPipeline, "execute"),
        patch.object(run_commands, "run_pr_review_agent"),
    ):
        run_result = runner.invoke(
            app,
            ["run", "code-review", "synthetic__style-018", "--repo-path", str(tmp_path), "--output-dir", str(tmp_path / "run")],
        )
        evaluate_result = runner.invoke(
            app,
            ["evaluate", "code-review", "synthetic__style-018", "--repo-path", str(tmp_path), "--output-dir", str(tmp_path / "evaluate")],
        )

    assert run_result.exit_code == 0
    assert evaluate_result.exit_code == 0
    assert "deprecated" in run_result.stderr.lower()
    assert "deprecated" in evaluate_result.stderr.lower()
