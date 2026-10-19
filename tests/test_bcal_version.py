import json
import subprocess
from collections.abc import Mapping
from typing import Any
from unittest.mock import PropertyMock, patch

import click
import pytest
import typer
from typer.main import get_command

from bcbench.agent.bcal.version import get_bcal_version, parse_bcal_version, verify_bcal_version
from bcbench.cli import app
from bcbench.commands import evaluate as evaluate_commands
from bcbench.dataset import NL2ALEntry
from bcbench.exceptions import AgentError
from bcbench.results import BaseEvaluationResult
from bcbench.types import EvaluationCategory

BCAL_VERSION = "18.0.38.47039-beta"
BCAL = {"packageId": "example.bcal.cli", "version": BCAL_VERSION, "commands": ["bcal"]}


def tools(*entries: Mapping[str, object]) -> str:
    return json.dumps({"version": 1, "data": list(entries)})


def test_reads_actual_nuget_version_without_normalizing_prerelease_or_fourth_component() -> None:
    other = {"packageId": "other.tool", "version": "9.9.9", "commands": ["other"]}

    assert parse_bcal_version(tools(other, BCAL)) == BCAL_VERSION


@pytest.mark.parametrize("expected", [BCAL_VERSION, f" {BCAL_VERSION} "])
def test_expected_version_is_checked_against_discovery(expected: str) -> None:
    verify_bcal_version(parse_bcal_version(tools(BCAL)), expected)


@pytest.mark.parametrize("expected", ["", " ", "latest", "1.*", "[1.2.3]", "1.2.3\n--prerelease"])
def test_invalid_expected_version_is_an_explicit_failure(expected: str) -> None:
    with pytest.raises(AgentError, match="exact, non-empty"):
        verify_bcal_version(BCAL_VERSION, expected)


def test_mismatched_expected_version_is_not_blindly_trusted() -> None:
    with pytest.raises(AgentError, match="does not match"):
        verify_bcal_version(BCAL_VERSION, "18.0.1.1-beta")


@pytest.mark.parametrize(
    "output",
    [
        tools(),
        tools(BCAL, BCAL),
        tools({**BCAL, "version": "latest"}),
        tools({**BCAL, "version": "1.2.3..preview"}),
        tools({**BCAL, "commands": ["not-bcal"]}),
        "not json",
        '{"version":2,"data":[]}',
        '{"version":1,"data":[{"packageId":"bcal","commands":["bcal"]}]}',
    ],
)
def test_missing_ambiguous_or_invalid_discovery_is_not_unknown_success(output: str) -> None:
    with pytest.raises(AgentError):
        parse_bcal_version(output)


def test_discovery_calls_structured_global_tool_list() -> None:
    completed = subprocess.CompletedProcess([], 0, stdout=tools(BCAL))
    with patch("bcbench.agent.bcal.version.subprocess.run", return_value=completed) as run:
        assert get_bcal_version() == BCAL_VERSION

    assert run.call_args.args[0] == ["dotnet", "tool", "list", "--global", "--format", "json"]
    assert run.call_args.kwargs["check"] is True
    assert run.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("error", [FileNotFoundError("dotnet missing"), subprocess.CalledProcessError(1, "dotnet"), subprocess.TimeoutExpired("dotnet", 30)])
def test_discovery_failure_is_explicit(error: Exception) -> None:
    with patch("bcbench.agent.bcal.version.subprocess.run", side_effect=error), pytest.raises(AgentError, match="Cannot discover"):
        get_bcal_version()


def test_evaluate_bcal_exposes_expected_version_option_and_environment_variable() -> None:
    root = get_command(app)
    assert isinstance(root, click.Group)
    evaluate = root.commands["evaluate"]
    assert isinstance(evaluate, click.Group)
    command = evaluate.commands["bcal"]
    option = next(parameter for parameter in command.params if parameter.name == "bcal_version")

    assert isinstance(option, click.Option)
    assert "--bcal-version" in option.opts
    assert option.envvar == "BCAL_PACKAGE_VERSION"


def test_expected_version_mismatch_saves_actual_version_without_running_agent(tmp_path) -> None:
    path = EvaluationCategory.NL2AL.dataset_path
    entry = NL2ALEntry.load(path)[0]

    class Pipeline:
        executed = False

        def execute(self, _context: Any, _agent_runner: Any) -> None:
            self.executed = True

        def save_result(self, context: Any, result: Any) -> None:
            result.save(context.result_dir, f"{context.entry.instance_id}.jsonl")

    pipeline = Pipeline()
    with (
        patch.object(EvaluationCategory, "pipeline", new_callable=PropertyMock, return_value=pipeline),
        patch.object(evaluate_commands, "get_bcal_version", return_value=BCAL_VERSION),
        patch.object(evaluate_commands, "run_bcal_agent") as run_agent,
        pytest.raises(typer.Exit) as failure,
    ):
        evaluate_commands.evaluate_bcal(
            entry.instance_id,
            repo_path=tmp_path / "work",
            output_dir=tmp_path / "out",
            run_id="run",
            llm_command="bridge",
            bcal_version="18.0.1.1-beta",
        )

    assert failure.value.exit_code == 1
    assert pipeline.executed is False
    run_agent.assert_not_called()
    result_path = tmp_path / "out" / "run" / f"{entry.instance_id}.jsonl"
    result = BaseEvaluationResult.from_json(json.loads(result_path.read_text(encoding="utf-8")))
    assert result.agent_version == BCAL_VERSION
    assert "does not match expected version" in (result.error_message or "")
