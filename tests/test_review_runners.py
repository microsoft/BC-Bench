from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from bcbench.agent import PRReviewHarness
from bcbench.cli import app
from bcbench.commands import evaluate as evaluate_commands
from bcbench.commands import run as run_commands
from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.types import EvaluationCategory, HarnessName


@pytest.mark.parametrize("harness_name", ["CopilotHarness", "ClaudeHarness"])
def test_generic_run_commands_accept_code_review(tmp_path: Path, harness_name: str) -> None:
    entry = object()
    command = run_commands.run_copilot if harness_name == "CopilotHarness" else run_commands.run_claude
    with (
        patch.object(CodeReviewEntry, "load", return_value=[entry]),
        patch.object(CodeReviewPipeline, "setup_workspace"),
        patch.object(run_commands, harness_name) as harness,
    ):
        command("synthetic__style-018", EvaluationCategory.CODE_REVIEW, repo_path=tmp_path, output_dir=tmp_path / "out")

    assert harness.call_args.kwargs["category"] is EvaluationCategory.CODE_REVIEW
    assert harness.return_value.run.call_args.args[0].task is entry


@pytest.mark.parametrize(
    ("command", "agent_name"),
    [
        (evaluate_commands.evaluate_copilot, HarnessName.COPILOT),
        (evaluate_commands.evaluate_claude_code, HarnessName.CLAUDE),
    ],
)
def test_generic_evaluate_commands_use_code_review_pipeline(tmp_path: Path, command, agent_name: HarnessName) -> None:
    contexts = []
    with (
        patch.object(CodeReviewEntry, "load", return_value=[object()]),
        patch.object(CodeReviewPipeline, "execute", side_effect=lambda context, _harness: contexts.append(context)),
        patch("bcbench.agent.copilot.agent.get_copilot_version", return_value="1.2.3"),
        patch("bcbench.agent.claude.agent.get_claude_version", return_value="1.2.3"),
    ):
        command(
            "synthetic__style-018",
            EvaluationCategory.CODE_REVIEW,
            repo_path=tmp_path,
            output_dir=tmp_path / "out",
            run_id=agent_name.name.lower(),
        )

    assert len(contexts) == 1
    assert contexts[0].agent.harness is agent_name
    assert contexts[0].agent.version == "1.2.3"
    assert contexts[0].category is EvaluationCategory.CODE_REVIEW


def test_pr_review_evaluation_is_fixed_to_runner_and_category(tmp_path: Path) -> None:
    executions = []
    with (
        patch.object(CodeReviewEntry, "load", return_value=[object()]),
        patch.object(CodeReviewPipeline, "execute", side_effect=lambda context, harness: executions.append((context, harness))),
        patch("bcbench.agent.pr_review.agent.get_pr_review_version", return_value="a" * 40) as get_version,
    ):
        result = CliRunner().invoke(
            app,
            [
                "evaluate",
                "pr-review",
                "synthetic__style-018",
                "--repo-path",
                str(tmp_path),
                "--output-dir",
                str(tmp_path / "out"),
                "--run-id",
                "pr-review",
                "--engine-path",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0, result.exception
    [(context, harness)] = executions
    assert harness == PRReviewHarness(model="gpt-5.6-luna", engine_path=tmp_path)
    assert context.agent.harness is HarnessName.PR_REVIEW
    assert context.agent.version == "a" * 40
    assert context.category is EvaluationCategory.CODE_REVIEW
    assert context.agent.model == "gpt-5.6-luna"
    get_version.assert_called_once_with(tmp_path)


def test_pr_review_run_is_fixed_to_code_review(tmp_path: Path) -> None:
    entry = object()
    with (
        patch.object(CodeReviewEntry, "load", return_value=[entry]),
        patch.object(CodeReviewPipeline, "setup_workspace"),
        patch.object(run_commands, "PRReviewHarness") as harness,
    ):
        result = CliRunner().invoke(
            app,
            [
                "run",
                "pr-review",
                "synthetic__style-018",
                "--repo-path",
                str(tmp_path),
                "--output-dir",
                str(tmp_path / "out"),
                "--engine-path",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 0, result.exception
    assert harness.call_args.kwargs["model"] == "gpt-5.6-luna"
    assert harness.call_args.kwargs["engine_path"] == tmp_path
    assert harness.return_value.run.call_args.args[0].task is entry


def test_pr_review_is_public_command() -> None:
    runner = CliRunner()

    run_help = runner.invoke(app, ["run", "--help"])
    evaluate_help = runner.invoke(app, ["evaluate", "--help"])

    assert run_help.exit_code == 0
    assert evaluate_help.exit_code == 0
    assert "pr-review" in run_help.stdout
    assert "pr-review" in evaluate_help.stdout
