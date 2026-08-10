from __future__ import annotations

import asyncio
import inspect
import logging
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Red teaming ships as the optional `redteam` dependency group, so skip when it is not installed.
pytest.importorskip("azure.ai.evaluation.red_team")

from bcbench import redteam
from bcbench.agent.bcal import BCalBackendConfig
from bcbench.agent.bcal import agent as bcal_agent
from bcbench.commands.redteam import _asr_table, _attack_result
from bcbench.exceptions import AgentError
from bcbench.types import BCalLLMBackend


@pytest.fixture
def bcal_target(tmp_path: Path) -> redteam.RedTeamCallback:
    with patch.object(redteam, "_ensure_package_cache"):
        return redteam.build_bcal_target(
            package_cache_path=tmp_path / ".alpackages",
            export_base=tmp_path / "exports",
            backend_config=BCalBackendConfig(backend=BCalLLMBackend.EXTERNAL_COMMAND, command="python bridge.py"),
        )


def test_bcal_target_uses_advanced_async_callback_signature(bcal_target: redteam.RedTeamCallback):
    assert inspect.iscoroutinefunction(bcal_target)
    assert tuple(inspect.signature(bcal_target).parameters) == ("messages", "stream", "session_state", "context")


def test_bcal_target_returns_assistant_response(bcal_target: redteam.RedTeamCallback):
    with patch.object(redteam, "run_bcal_prompt", return_value="generated AL") as run_prompt:
        result = asyncio.run(bcal_target(messages=[{"role": "user", "content": "attack prompt"}]))

    assert result["messages"] == [{"role": "assistant", "content": "generated AL"}]
    assert run_prompt.call_args.args[1] == "attack prompt"


def test_bcal_target_runs_concurrent_prompts_in_parallel(bcal_target: redteam.RedTeamCallback):
    processes_started = threading.Barrier(2, timeout=5)
    export_folders: list[str] = []

    def wait_for_other_process(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        export_folders.extend(arg for arg in args if arg.startswith("--exportfolder="))
        processes_started.wait()
        return subprocess.CompletedProcess(args, 0, stdout="generated AL", stderr="")

    async def run_concurrently() -> tuple[dict[str, object], dict[str, object]]:
        return await asyncio.gather(
            bcal_target(messages=[{"role": "user", "content": "first"}]),
            bcal_target(messages=[{"role": "user", "content": "second"}]),
        )

    with (
        patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"),
        patch.object(subprocess, "run", side_effect=wait_for_other_process),
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


def test_run_scan_raises_target_error_swallowed_by_sdk(tmp_path: Path):
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
        pytest.raises(AgentError, match="bcal failed"),
    ):
        redteam.run_scan(failing_target, {}, tmp_path / "scorecard", "test-scan")


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
            return SimpleNamespace(attack_details=[{}])

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


def test_asr_table_reports_every_group_in_the_sdk_summary():
    table = _asr_table(
        "t", [{"overall_asr": 50.0, "overall_total": 2, "overall_successful_attacks": 1, "code_vulnerability_asr": 50.0, "code_vulnerability_total": 2, "code_vulnerability_successful_attacks": 1}]
    )

    assert table is not None
    assert list(table.columns[0].cells) == ["code_vulnerability", "overall"]


def test_asr_table_skips_summaries_without_asr_keys():
    assert _asr_table("t", []) is None
    assert _asr_table("t", [{"unrelated": 1}]) is None
