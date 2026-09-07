from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from bcbench.cli import app
from bcbench.commands import evaluate as evaluate_commands
from bcbench.commands import run as run_commands
from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.exceptions import AgentError
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
        patch.object(evaluate_commands, "get_copilot_version", return_value="1.2.3"),
        patch.object(evaluate_commands, "get_claude_version", return_value="1.2.3"),
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
    assert contexts[0].agent_version == "1.2.3"
    assert contexts[0].category is EvaluationCategory.CODE_REVIEW


def test_pr_review_evaluation_is_fixed_to_runner_and_category(tmp_path: Path) -> None:
    contexts = []
    with (
        patch.object(CodeReviewEntry, "load", return_value=[object()]),
        patch.object(CodeReviewPipeline, "execute", side_effect=lambda context, runner: (contexts.append(context), runner(context))),
        patch.object(evaluate_commands, "run_pr_review_agent") as agent_runner,
        patch.object(evaluate_commands, "get_pr_review_version", return_value="a" * 40) as get_version,
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
    assert len(contexts) == 1
    assert contexts[0].agent_name is AgentHarness.PR_REVIEW
    assert contexts[0].agent_version == "a" * 40
    assert contexts[0].category is EvaluationCategory.CODE_REVIEW
    assert contexts[0].model == "gpt-5.6-luna"
    assert agent_runner.call_args.kwargs["engine_path"] == tmp_path
    get_version.assert_called_once_with(tmp_path)


@pytest.mark.parametrize("harness", ["copilot", "claude", "pr-review"])
def test_evaluation_does_not_start_when_version_resolution_fails(tmp_path: Path, harness: str) -> None:
    resolver = f"get_{harness.replace('-', '_')}_version"
    with (
        patch.object(CodeReviewEntry, "load", return_value=[object()]),
        patch.object(CodeReviewPipeline, "execute") as execute,
        patch.object(evaluate_commands, resolver, side_effect=AgentError("Version unavailable")),
    ):
        args = ["evaluate", harness, "synthetic__style-018", "--output-dir", str(tmp_path)]
        if harness != "pr-review":
            args.extend(["--category", "code-review"])
        result = CliRunner().invoke(app, args)

    assert result.exit_code != 0
    assert isinstance(result.exception, AgentError)
    execute.assert_not_called()


def test_pr_review_run_is_fixed_to_code_review(tmp_path: Path) -> None:
    entry = object()
    with (
        patch.object(CodeReviewEntry, "load", return_value=[entry]),
        patch.object(CodeReviewPipeline, "setup_workspace"),
        patch.object(run_commands, "run_pr_review_agent") as agent_runner,
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
    assert agent_runner.call_args.kwargs["entry"] is entry
    assert agent_runner.call_args.kwargs["category"] is EvaluationCategory.CODE_REVIEW
    assert agent_runner.call_args.kwargs["model"] == "gpt-5.6-luna"
    assert agent_runner.call_args.kwargs["engine_path"] == tmp_path


def test_pr_review_is_public_command() -> None:
    runner = CliRunner()

    run_help = runner.invoke(app, ["run", "--help"])
    evaluate_help = runner.invoke(app, ["evaluate", "--help"])

    assert run_help.exit_code == 0
    assert evaluate_help.exit_code == 0
    assert "pr-review" in run_help.stdout
    assert "pr-review" in evaluate_help.stdout


def test_pr_review_severity_override_is_only_available_for_smoke_tests() -> None:
    runner = CliRunner()
    run_help = runner.invoke(app, ["run", "pr-review", "--help"])
    evaluate_help = runner.invoke(app, ["evaluate", "pr-review", "--help"])

    assert run_help.exit_code == evaluate_help.exit_code == 0
    assert "min-severity" in run_help.stdout
    assert "min-severity" not in evaluate_help.stdout
