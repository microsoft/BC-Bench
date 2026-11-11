from __future__ import annotations

import asyncio
import inspect
import json
import logging
import subprocess
import threading
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import click
import pytest
from bcbench_core.exceptions import AgentError
from rich.console import Console
from typer.main import get_command

# Red teaming ships as the optional `redteam` extra, so skip when it is not installed.
pytest.importorskip("azure.ai.evaluation.red_team")

from bcbench import redteam
from bcbench.agent.bcal import BCalAgentRuntime, BCalBackendConfig
from bcbench.agent.bcal import agent as bcal_agent
from bcbench.commands import redteam as redteam_commands
from bcbench.commands.redteam import _asr_table, _attack_result, _rows_table, redteam_app


@pytest.fixture
def bcal_target(tmp_path: Path) -> redteam.RedTeamCallback:
    with patch.object(redteam, "_ensure_package_cache"):
        return redteam.build_bcal_target(
            package_cache_path=tmp_path / ".alpackages",
            export_base=tmp_path / "exports",
            backend_config=BCalBackendConfig(command="python bridge.py"),
        )


def _option_names(command: click.Command) -> set[str]:
    return {option for parameter in command.params if isinstance(parameter, click.Option) for option in (*parameter.opts, *parameter.secondary_opts)}


def test_scan_only_exposes_external_command_options():
    root = get_command(redteam_app)
    assert isinstance(root, click.Group)
    options = _option_names(root.commands["scan"])

    assert {
        "--llm-command",
        "--llm-model",
        "--agent-runtime",
        "--agent-planning",
        "--sdk-provider",
        "--sdk-base-url",
        "--sdk-model",
        "--sdk-api-key-env",
        "--sdk-reasoning-effort",
        "--sdk-max-model-requests",
        "--sdk-timeout-seconds",
        "--inference-provider",
        "--llm-provider",
        "--llm-wire-api",
    } <= options
    assert options.isdisjoint({"--backend", "--endpoint", "--deployment"})


@pytest.mark.parametrize("fails", [False, True])
def test_scan_forwards_sdk_contract_and_persists_terminal_metadata(tmp_path: Path, monkeypatch, fails):
    monkeypatch.setenv("TEST_SDK_KEY", "not-a-real-key")
    output = tmp_path / "scorecard"
    with (
        patch.object(redteam, "build_bcal_target") as build,
        patch.object(redteam, "run_scan", side_effect=AgentError("scan failed") if fails else None),
        patch.object(redteam_commands, "_load_scorecard"),
        patch.object(redteam_commands, "_render_scorecard"),
        patch.object(bcal_agent, "get_bcal_version", return_value="sdk-test-package"),
    ):
        args = {
            "subscription_id": "test-subscription",
            "resource_group": "test-group",
            "project_name": "test-project",
            "language": next(iter(redteam.SupportedLanguages)),
            "risk_category": [next(iter(redteam.RiskCategory))],
            "agent_runtime": BCalAgentRuntime.COPILOT_SDK,
            "agent_planning": "bcal",
            "sdk_provider": "openai",
            "sdk_base_url": "http://127.0.0.1:8123/v1",
            "sdk_model": "main-model",
            "sdk_api_key_env": "TEST_SDK_KEY",
            "sdk_reasoning_effort": "low",
            "sdk_max_model_requests": 12,
            "sdk_timeout_seconds": 180,
            "inference_provider": "main-provider",
            "llm_command": "python auxiliary.py",
            "llm_model": "auxiliary-model",
            "llm_provider": "auxiliary-provider",
            "llm_wire_api": "chat-completions",
            "output": output,
            "scan_name": "fixed-test-scan",
        }
        if fails:
            with pytest.raises(AgentError, match="scan failed"):
                redteam_commands.scan(**args)
        else:
            redteam_commands.scan(**args)
    config = build.call_args.kwargs["backend_config"]
    assert "--sdk-max-model-requests=12" in config.cli_args()
    assert "--sdk-timeout-seconds=180" in config.cli_args()
    assert "--agent-planning=bcal" in config.cli_args()
    metadata = json.loads((tmp_path / "scorecard.execution.json").read_text())
    assert metadata["scanTerminal"] == ("failed" if fails else "completed")
    assert metadata["bcalVersion"] == "sdk-test-package"
    assert metadata["model"] == "main-model"
    assert metadata["execution"]["main"]["provider"] == "main-provider"
    assert metadata["execution"]["planning"]["planningMode"] == "bcal"
    assert metadata["execution"]["auxiliary"]["provider"] == "auxiliary-provider"
    assert "not-a-real-key" not in json.dumps(metadata)


def test_bcal_target_uses_advanced_async_callback_signature(bcal_target: redteam.RedTeamCallback):
    assert inspect.iscoroutinefunction(bcal_target)
    assert tuple(inspect.signature(bcal_target).parameters) == ("messages", "stream", "session_state", "context")


def test_bcal_target_returns_assistant_response(bcal_target: redteam.RedTeamCallback):
    with patch.object(redteam, "run_bcal_prompt", return_value="generated AL") as run_prompt:
        result = asyncio.run(bcal_target(messages=[{"role": "user", "content": "attack prompt"}]))

    assert result["messages"] == [{"role": "assistant", "content": "generated AL"}]
    assert run_prompt.call_args.args[1] == "attack prompt"


def test_bcal_target_sends_the_latest_attack_prompt(bcal_target: redteam.RedTeamCallback):
    messages = [
        {"role": "user", "content": "first request"},
        {"role": "assistant", "content": "first response"},
        {"role": "user", "content": "follow-up request"},
    ]

    with patch.object(redteam, "run_bcal_prompt", return_value="generated AL") as run_prompt:
        asyncio.run(bcal_target(messages=messages))

    assert run_prompt.call_args.args[1] == "follow-up request"


@pytest.mark.parametrize("is_agent_target", [False, True])
def test_run_scan_forwards_the_target_type_to_the_sdk(tmp_path: Path, is_agent_target: bool):
    captured: dict[str, object] = {}

    async def unused_target(**_kwargs: object) -> dict[str, object]:
        return {"messages": []}

    class FakeRedTeam:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def scan(self, **kwargs: object) -> SimpleNamespace:
            captured.update(kwargs)
            return SimpleNamespace(attack_details=[{"attack_success": False}])

    with patch.object(redteam, "RedTeam", FakeRedTeam), patch.object(redteam, "DefaultAzureCredential"):
        redteam.run_scan(unused_target, {}, tmp_path / "scorecard", "test-scan", is_agent_target=is_agent_target)

    assert captured["is_agent_target"] is is_agent_target


def test_bcal_target_runs_concurrent_prompts_in_parallel(bcal_target: redteam.RedTeamCallback):
    processes_started = threading.Barrier(2, timeout=5)
    export_folders: list[str] = []

    def wait_for_other_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        export_folders.extend(arg for arg in args if arg.startswith("--exportfolder="))
        processes_started.wait()
        prompt = next(arg.removeprefix("--prompt=") for arg in args if arg.startswith("--prompt="))
        return subprocess.CompletedProcess(args, 0, stdout=f"> {prompt}\ngenerated AL", stderr="")

    async def run_concurrently() -> tuple[dict[str, object], dict[str, object]]:
        return await asyncio.gather(
            bcal_target(messages=[{"role": "user", "content": "first"}]),
            bcal_target(messages=[{"role": "user", "content": "second"}]),
        )

    with (
        patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
        patch.object(bcal_agent, "_run_bcal_process", side_effect=wait_for_other_process),
    ):
        results = asyncio.run(run_concurrently())

    assert [result["messages"] for result in results] == [
        [{"role": "assistant", "content": "generated AL"}],
        [{"role": "assistant", "content": "generated AL"}],
    ]
    assert len(export_folders) == len(set(export_folders)) == 2


def test_bcal_target_propagates_execution_errors(bcal_target: redteam.RedTeamCallback):
    with (
        patch.object(redteam, "run_bcal_prompt", side_effect=AgentError("bcal failed")),
        pytest.raises(AgentError, match="bcal failed"),
    ):
        asyncio.run(bcal_target(messages=[{"role": "user", "content": "attack prompt"}]))


def test_run_scan_reports_target_failure_that_produced_no_results(tmp_path: Path):
    async def failing_target(**_kwargs: object) -> dict[str, object]:
        raise AgentError("bcal failed")

    class FakeRedTeam:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def scan(self, *, target: redteam.RedTeamCallback, **_kwargs: object) -> SimpleNamespace:
            with pytest.raises(AgentError):
                await target(messages=[])
            return SimpleNamespace(attack_details=[])

    with (
        patch.object(redteam, "RedTeam", FakeRedTeam),
        patch.object(redteam, "DefaultAzureCredential"),
        pytest.raises(RuntimeError, match="without any evaluated attacks") as exc_info,
    ):
        redteam.run_scan(failing_target, {}, tmp_path / "scorecard", "test-scan")

    assert isinstance(exc_info.value.__cause__, AgentError)


def test_run_scan_marks_a_recovered_retry_as_successful(tmp_path: Path):
    calls = 0

    async def rate_limited_once(**_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AgentError("429 Too Many Requests")
        return {"messages": [{"role": "assistant", "content": "generated AL"}]}

    class FakeRedTeam:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def scan(self, *, target: redteam.RedTeamCallback, **_kwargs: object) -> SimpleNamespace:
            with pytest.raises(AgentError, match="429"):
                await target(messages=[])
            await target(messages=[])
            return SimpleNamespace(attack_details=[{"attack_success": False}])

    with patch.object(redteam, "RedTeam", FakeRedTeam), patch.object(redteam, "DefaultAzureCredential"):
        redteam.run_scan(rate_limited_once, {}, tmp_path / "scorecard", "test-scan")

    assert calls == 2


def test_run_scan_rejects_empty_results(tmp_path: Path):
    async def unused_target(**_kwargs: object) -> dict[str, object]:
        return {"messages": []}

    class FakeRedTeam:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def scan(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(attack_details=[])

    with (
        patch.object(redteam, "RedTeam", FakeRedTeam),
        patch.object(redteam, "DefaultAzureCredential"),
        pytest.raises(RuntimeError, match="without any evaluated attacks"),
    ):
        redteam.run_scan(unused_target, {}, tmp_path / "scorecard", "test-scan")


def test_run_scan_rejects_wholly_unevaluated_results(tmp_path: Path):
    async def unused_target(**_kwargs: object) -> dict[str, object]:
        return {"messages": []}

    class FakeRedTeam:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def scan(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(attack_details=[{"attack_success": None}])

    with (
        patch.object(redteam, "RedTeam", FakeRedTeam),
        patch.object(redteam, "DefaultAzureCredential"),
        pytest.raises(RuntimeError, match="without any evaluated attacks"),
    ):
        redteam.run_scan(unused_target, {}, tmp_path / "scorecard", "test-scan")


def test_run_scan_writes_unicode_target_output_to_sdk_log(tmp_path: Path):
    log_path = tmp_path / "redteam.log"
    sdk_logger = logging.getLogger("RedTeamLogger")
    original_handlers = sdk_logger.handlers[:]
    original_level = sdk_logger.level
    original_propagate = sdk_logger.propagate

    async def successful_target(**_kwargs: object) -> dict[str, object]:
        return {"messages": [{"role": "assistant", "content": "● generated AL"}]}

    class FakeRedTeam:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def scan(self, *, target: redteam.RedTeamCallback, **_kwargs: object) -> SimpleNamespace:
            sdk_logger.addHandler(logging.FileHandler(log_path, encoding="cp1252"))
            sdk_logger.setLevel(logging.DEBUG)
            await target(messages=[])
            sdk_logger.debug("RAI evaluation result: ● generated AL")
            return SimpleNamespace(attack_details=[{"attack_success": False}])

    sdk_logger.handlers.clear()
    sdk_logger.propagate = False
    try:
        with patch.object(redteam, "RedTeam", FakeRedTeam), patch.object(redteam, "DefaultAzureCredential"):
            redteam.run_scan(successful_target, {}, tmp_path / "scorecard", "test-scan")
    finally:
        for handler in sdk_logger.handlers:
            handler.close()
        sdk_logger.handlers = original_handlers
        sdk_logger.setLevel(original_level)
        sdk_logger.propagate = original_propagate

    assert "RAI evaluation result: ● generated AL" in log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("attack_success", "label"),
    [
        (True, "broke"),
        (False, "resisted"),
        (None, "unevaluated"),
    ],
)
def test_attack_result_preserves_all_sdk_states(attack_success: bool | None, label: str):
    assert label in _attack_result(attack_success)


def test_rows_table_renders_attack_text_as_literal_content():
    output = StringIO()
    console = Console(file=output, color_system=None, width=200)
    details = [
        {
            "attack_success": False,
            "conversation": [
                {"role": "user", "content": "[/] attack"},
                {"role": "assistant", "content": "[red]literal response[/red]"},
            ],
        }
    ]

    console.print(_rows_table(details))

    assert "[/] attack" in output.getvalue()
    assert "[red]literal response[/red]" in output.getvalue()


def test_asr_table_reports_every_group_in_the_sdk_summary():
    table = _asr_table(
        "t", [{"overall_asr": 50.0, "overall_total": 2, "overall_successful_attacks": 1, "code_vulnerability_asr": 50.0, "code_vulnerability_total": 2, "code_vulnerability_successful_attacks": 1}]
    )

    assert table is not None
    assert list(table.columns[0].cells) == ["code_vulnerability", "overall"]


def test_asr_table_skips_summaries_without_asr_keys():
    assert _asr_table("t", []) is None
    assert _asr_table("t", [{"unrelated": 1}]) is None
