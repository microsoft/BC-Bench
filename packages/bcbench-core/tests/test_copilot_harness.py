from enum import StrEnum
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench_core.agent.copilot import CopilotHarness, CopilotOptions, CopilotTimeoutError
from bcbench_core.agent.experiment import ExperimentConfiguration
from bcbench_core.agent.harness import AgentRequest
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.exceptions import AgentTimeoutError


def test_identity_reports_copilot_version_and_model():
    with patch("bcbench_core.agent.copilot.harness.get_copilot_version", return_value="1.0.98"):
        identity = CopilotHarness(name="copilot", model="test-model", env={}).identity()

    assert (identity.harness, identity.version, identity.model) == ("copilot", "1.0.98", "test-model")


def test_run_sends_the_task_as_prompt_and_logs_to_output_dir(tmp_path: Path):
    metrics = AgentMetrics(execution_time=1.5)
    env = {"PATH": "x"}
    request = AgentRequest(task="Q", work_dir=tmp_path, output_dir=tmp_path / "logs", timeout=60)

    with patch("bcbench_core.agent.copilot.harness.invoke_copilot", return_value=(metrics, "A")) as invoke:
        result = CopilotHarness(name="copilot", model="test-model", env=env, options=CopilotOptions(allow_all_tools=True)).run(request)

    assert (result.response, result.metrics) == ("A", metrics)
    assert invoke.call_args.kwargs == {
        "prompt": "Q",
        "model": "test-model",
        "work_dir": tmp_path,
        "timeout": 60,
        "env": env,
        "options": CopilotOptions(allow_all_tools=True, log_dir=tmp_path / "logs"),
    }


def test_run_falls_back_to_harness_timeout(tmp_path: Path):
    with patch("bcbench_core.agent.copilot.harness.invoke_copilot", return_value=(None, "")) as invoke:
        CopilotHarness(name="copilot", model="m", env={}, timeout=42).run(AgentRequest(task="Q", work_dir=tmp_path, output_dir=tmp_path))

    assert invoke.call_args.kwargs["timeout"] == 42


def test_timeout_raises_harness_neutral_error_with_metrics(tmp_path: Path):
    with (
        patch("bcbench_core.agent.copilot.harness.invoke_copilot", side_effect=CopilotTimeoutError(60)),
        pytest.raises(AgentTimeoutError) as exc_info,
    ):
        CopilotHarness(name="copilot", model="m", env={}).run(AgentRequest(task="Q", work_dir=tmp_path, output_dir=tmp_path))

    assert exc_info.value.metrics == AgentMetrics(execution_time=60)


class Name(StrEnum):
    COPILOT = "GitHub Copilot"


def test_identity_keeps_the_given_name_type():
    with patch("bcbench_core.agent.copilot.harness.get_copilot_version", return_value="1.0.98"):
        identity = CopilotHarness(name=Name.COPILOT, model="m", env={}).identity()

    assert identity.harness is Name.COPILOT


def test_experiment_is_reported_with_results_and_timeouts(tmp_path: Path):
    experiment = ExperimentConfiguration(mcp_servers=["probe"])
    harness = CopilotHarness(name="copilot", model="m", env={}, experiment=experiment)
    request = AgentRequest(task="Q", work_dir=tmp_path, output_dir=tmp_path)

    with patch("bcbench_core.agent.copilot.harness.invoke_copilot", return_value=(None, "A")):
        assert harness.run(request).experiment == experiment
    with patch("bcbench_core.agent.copilot.harness.invoke_copilot", side_effect=CopilotTimeoutError(60)), pytest.raises(AgentTimeoutError) as exc_info:
        harness.run(request)
    assert exc_info.value.config == experiment
