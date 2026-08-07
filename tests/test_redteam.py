from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench import redteam
from bcbench.agent.bcal import BCalBackendConfig
from bcbench.commands.redteam import _attack_result
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


def test_bcal_target_propagates_execution_errors(bcal_target: redteam.RedTeamCallback):
    with (
        patch.object(redteam, "run_bcal_prompt", side_effect=AgentError("bcal failed")),
        pytest.raises(AgentError, match="bcal failed"),
    ):
        asyncio.run(bcal_target(messages=[{"role": "user", "content": "attack prompt"}]))


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
