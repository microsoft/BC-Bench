import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from bcbench.agent.bcal import BCalBackendConfig
from bcbench.agent.bcal import agent as bcal_agent
from bcbench.agent.bcal.scenario import BCalScenarioError
from bcbench.dataset import NL2ALEntry
from bcbench.dataset.dataset_entry import NL2ALTurn
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.types import ChecklistAssertion
from tests.conftest import create_nl2al_entry


@pytest.fixture
def entry():
    turns = [
        NL2ALTurn(
            prompt='Tilføj feltet "Budget" til kundekortet.\nBevar de eksisterende felter.',
            intent="customize",
            expected=[ChecklistAssertion(text="HIDDEN_INITIAL_ASSERTION", level="critical")],
        ),
        NL2ALTurn(prompt="  Tilfoej en tooltip.  ", intent="customize", expected=[ChecklistAssertion(text="HIDDEN_TOOLTIP_ASSERTION", level="critical")]),
        NL2ALTurn(
            prompt='Kald det nye felt "Årsbudget".',
            intent="customize",
            expected=[ChecklistAssertion(text="HIDDEN_RENAME_ASSERTION", level="critical")],
        ),
        NL2ALTurn(prompt="Flyt feltet efter Name.", intent="customize", expected=[ChecklistAssertion(text="HIDDEN_FINAL_ASSERTION", level="critical")]),
    ]
    base = create_nl2al_entry(nl_prompt=turns[0].prompt, expected=turns[-1].expected, audience="Technical")
    return NL2ALEntry.model_validate({**base.model_dump(), "turns": turns, "language": "da-DK"})


@pytest.fixture
def workspace(tmp_path: Path, entry: NL2ALEntry):
    workspace = tmp_path / "repositories" / entry.instance_id / "workspace"
    (workspace / entry.project_paths[0] / ".alpackages").mkdir(parents=True)
    return workspace


@pytest.fixture(autouse=True)
def bcal_executable():
    with patch.object(bcal_agent, "_resolve_bcal_executable", return_value="C:\\fake\\bcal.exe"):
        yield


@pytest.fixture(autouse=True)
def scenario_help():
    with patch.object(bcal_agent.subprocess, "check_output", return_value="Options:\n  --scenario <JSON>\n  --result <JSON>") as probe:
        yield probe


def native_result(statuses: tuple[str, ...] = ("succeeded",) * 4) -> dict[str, Any]:
    tool_usage = [{"name": "compile", "started": 1, "completed": 1, "succeeded": 1, "failed": 0}]
    return {
        "schemaVersion": "1.0",
        "completed": True,
        "steps": [
            {
                "id": f"turn-{index}",
                "type": "user",
                "status": status,
                "assistantText": "Completed the requested turn.",
                "compileSucceeded": True,
                "plan": None,
                "tokens": {"input": 100, "output": 40},
                "durationMs": 1200,
                "toolUsage": tool_usage,
                "failure": None,
            }
            for index, status in enumerate(statuses, 1)
        ],
        "interactions": [],
        "toolUsage": [{"name": "compile", "started": len(statuses), "completed": len(statuses), "succeeded": len(statuses), "failed": 0}],
        "totals": {
            "steps": len(statuses),
            "successfulSteps": statuses.count("succeeded"),
            "failedSteps": statuses.count("failed"),
            "inputTokens": len(statuses) * 100,
            "outputTokens": len(statuses) * 40,
            "toolCallsStarted": len(statuses),
            "toolCallsCompleted": len(statuses),
            "durationMs": len(statuses) * 1200 + 200,
        },
        "export": {"attempted": True, "success": True, "path": "exported-app", "filesExported": 4, "message": "Exported."},
        "sessionArchive": {
            "attempted": True,
            "success": True,
            "path": "bcal-session.zip",
            "fileName": "bcal-session.zip",
            "entriesExported": 7,
            "chatEntryPath": "chat.json",
            "message": "Session archive created.",
        },
        "failure": None,
    }


def argument_path(args: list[str], flag: str) -> Path:
    return Path(next(argument.removeprefix(flag) for argument in args if argument.startswith(flag)))


def save_result(args: list[str], payload: dict[str, Any]) -> None:
    result_path = argument_path(args, "--result=")
    payload["export"]["path"] = str(argument_path(args, "--exportfolder="))
    payload["sessionArchive"]["path"] = str(result_path.parent / "bcal-session.zip")
    result_path.write_text(json.dumps(payload), encoding="utf-8")


def invoke(entry: NL2ALEntry, workspace: Path, result_dir: Path | None):
    return bcal_agent.run_bcal_agent(entry, workspace, BCalBackendConfig(command="python bridge.py", model="gpt-5"), result_dir=result_dir)


def test_unmapped_interaction_is_rejected_before_process(entry: NL2ALEntry, workspace: Path, tmp_path: Path):
    data = entry.model_dump()
    data["turns"][1] = {"prompt": "Inspect only", "intent": "inspect", "expected": []}
    mixed = NL2ALEntry.model_validate(data)
    with patch.object(bcal_agent.subprocess, "run") as process, pytest.raises(AgentError, match="interaction/context mappings"):
        invoke(mixed, workspace, tmp_path / "results")
    process.assert_not_called()


@pytest.mark.parametrize("compile_succeeded", [False, None])
def test_customization_step_requires_observed_compilation(entry: NL2ALEntry, workspace: Path, tmp_path: Path, compile_succeeded):
    payload = native_result()
    payload["steps"][1]["compileSucceeded"] = compile_succeeded

    def fake_run(args: list[str], **_: object):
        save_result(args, payload)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run), pytest.raises(BCalScenarioError, match="successful compilation"):
        invoke(entry, workspace, tmp_path / "results")


def test_all_turns_use_one_native_session_with_isolated_artifacts(entry: NL2ALEntry, workspace: Path, tmp_path: Path, scenario_help):
    payload = native_result()

    def fake_run(args: list[str], **_: object):
        save_result(args, payload)
        argument_path(args, "--result=").with_name("bcal-session.zip").write_bytes(b"mock sanitized session archive")
        return subprocess.CompletedProcess(args, 0, stdout="All turns finished", stderr="native diagnostic")

    with (
        patch.object(bcal_agent.subprocess, "run", side_effect=fake_run) as process,
        patch.object(NL2ALEntry, "get_task", side_effect=AssertionError("Judge context must not be executed")),
    ):
        metrics, config = invoke(entry, workspace, tmp_path / "results")

    process.assert_called_once()
    scenario_help.assert_called_once_with(
        ["C:\\fake\\bcal.exe", "--help"],
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        timeout=30,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    args = process.call_args.args[0]
    assert args[0] == "C:\\fake\\bcal.exe"
    assert "--llm-backend=external-command" in args
    assert "--llm-command=python bridge.py" in args
    assert "--deployment=gpt-5" in args
    assert not any(argument.startswith("--prompt=") for argument in args)
    assert argument_path(args, "--packagecachepath=") == workspace / entry.project_paths[0] / ".alpackages"
    assert argument_path(args, "--exportfolder=") == workspace / entry.project_paths[0] / bcal_agent._config.file_patterns.nl2al_export_subdir
    assert process.call_args.kwargs["timeout"] == bcal_agent._config.timeout.bcal_execution
    assert process.call_args.kwargs["stdin"] == subprocess.DEVNULL
    assert process.call_args.kwargs["check"] is True

    scenario_path = argument_path(args, "--scenario=")
    result_path = argument_path(args, "--result=")
    assert scenario_path.parent == result_path.parent
    assert scenario_path.parent.parent == tmp_path / "results" / "bcal-scenario" / entry.instance_id
    assert not scenario_path.is_relative_to(workspace)
    assert {path.name for path in scenario_path.parent.iterdir()} == {"scenario.json", "result.json", "bcal-session.zip", "stdout.log", "stderr.log"}
    assert result_path.with_name("stdout.log").read_text(encoding="utf-8") == "All turns finished"
    assert result_path.with_name("stderr.log").read_text(encoding="utf-8") == "native diagnostic"
    assert not any(path.is_file() for path in workspace.rglob("*"))

    scenario_text = scenario_path.read_text(encoding="utf-8")
    scenario = json.loads(scenario_text)
    assert scenario["schemaVersion"] == "1.0"
    assert scenario["session"] == {
        "publisher": "bcal",
        "mode": "extension",
        "audience": "technical",
        "page": entry.page,
        "locale": "da-DK",
        "publish": "never",
        "review": True,
    }
    assert scenario["steps"] == [{"id": f"turn-{index}", "type": "user", "text": turn.prompt} for index, turn in enumerate(entry.turns, 1)]
    assert scenario["interactions"] == [{"id": "unexpected-clarification", "match": {"default": True}, "response": {"action": "cancel"}}]
    for private_value in ("HIDDEN_INITIAL_ASSERTION", "HIDDEN_FINAL_ASSERTION", '"expected"', '"intent"', "python bridge.py", "gpt-5"):
        assert private_value not in scenario_text
    assert metrics is not None
    assert metrics.turn_count == 4
    assert metrics.prompt_tokens == 400
    assert metrics.completion_tokens == 160
    assert metrics.total_tokens == 560
    assert metrics.tool_usage == {"compile": 4}
    assert metrics.execution_time is not None
    assert metrics.execution_time >= 0
    assert config.is_empty()


@pytest.mark.parametrize(
    ("help_text", "missing"),
    [
        ("bcal 18.0.38.47039-beta\nOptions:\n  --prompt <PROMPT>\n  --version", "--scenario, --result"),
        ("Options:\n  --scenario <JSON>\n  --result-folder <PATH>", "--result"),
        ("Options:\n  --scenario-file <JSON>\n  --result <JSON>", "--scenario"),
        ("", "--scenario, --result"),
    ],
)
def test_missing_native_capabilities_fail_before_model_or_artifact_creation(entry: NL2ALEntry, workspace: Path, tmp_path: Path, scenario_help, help_text: str, missing: str):
    scenario_help.return_value = help_text
    with patch.object(bcal_agent.subprocess, "run") as process, pytest.raises(AgentError, match="does not advertise native multi-turn") as failure:
        invoke(entry, workspace, tmp_path / "results")

    scenario_help.assert_called_once()
    process.assert_not_called()
    assert f"--help is missing {missing}." in str(failure.value)
    assert "No model was invoked" in str(failure.value)
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize(
    "probe_failure",
    [
        subprocess.CalledProcessError(2, ["bcal", "--help"], output="--scenario --result"),
        subprocess.TimeoutExpired(["bcal", "--help"], 30, output=b"--scenario --result"),
        OSError("Cannot start help probe"),
    ],
)
def test_failed_capability_probe_fails_closed(entry: NL2ALEntry, workspace: Path, tmp_path: Path, scenario_help, probe_failure: Exception):
    scenario_help.side_effect = probe_failure
    with patch.object(bcal_agent.subprocess, "run") as process, pytest.raises(AgentError, match="Cannot verify native BCAL scenario support") as failure:
        invoke(entry, workspace, tmp_path / "results")

    process.assert_not_called()
    assert "No model was invoked" in str(failure.value)
    assert not (tmp_path / "results").exists()


def test_capability_probe_accepts_equals_option_notation(entry: NL2ALEntry, workspace: Path, tmp_path: Path, scenario_help):
    scenario_help.return_value = "Options:\n  --scenario=<JSON>\n  --result=<JSON>"

    def fake_run(args: list[str], **_: object):
        save_result(args, native_result())
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run) as process:
        invoke(entry, workspace, tmp_path / "results")

    scenario_help.assert_called_once()
    process.assert_called_once()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda result: result.update(completed=False), "did not complete"),
        (lambda result: result.update(failure={"code": "model_failed", "message": "Backend failed"}), "model_failed: Backend failed"),
        (lambda result: result["steps"][1].update(status="failed"), "turn-2: type=user, status=failed"),
        (lambda result: result["steps"][1].update(status="skipped"), "turn-2: type=user, status=skipped"),
        (lambda result: result["steps"][1].update(status="unknown"), "turn-2: type=user, status=unknown"),
        (lambda result: result["steps"][1].update(type="plan_action"), "turn-2: type=plan_action"),
        (lambda result: result["steps"][1].update(failure={"code": "turn_failed", "message": "Bad turn", "stepId": "turn-2"}), r"turn_failed \(turn-2\): Bad turn"),
        (lambda result: result["steps"].pop(), "scripted turn order"),
        (lambda result: result["steps"][1].update(id="turn-1"), "scripted turn order"),
        (lambda result: result["steps"].reverse(), "scripted turn order"),
        (lambda result: result["steps"].append({**result["steps"][0], "id": "turn-5"}), "scripted turn order"),
        (lambda result: result["export"].update(attempted=False), "export failed or was not attempted"),
        (lambda result: result["export"].update(success=False, message="Could not write AL"), "Could not write AL"),
        (lambda result: result["sessionArchive"].update(attempted=False), "session archive failed or was not attempted"),
        (lambda result: result["sessionArchive"].update(success=False, message="Could not write archive"), "Could not write archive"),
        (lambda result: result["totals"].update(steps=3), "totals do not match"),
        (lambda result: result["totals"].update(successfulSteps=3), "totals do not match"),
        (lambda result: result["totals"].update(failedSteps=1), "totals do not match"),
    ],
)
def test_zero_exit_does_not_override_failed_native_result(entry: NL2ALEntry, workspace: Path, tmp_path: Path, mutate, message: str):
    payload = native_result()
    mutate(payload)

    def fake_run(args: list[str], **_: object):
        save_result(args, payload)
        return subprocess.CompletedProcess(args, 0, stdout="Backend returned", stderr="")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run), pytest.raises(BCalScenarioError, match=message) as failure:
        invoke(entry, workspace, tmp_path / "results")

    assert failure.value.metrics.execution_time is not None
    assert failure.value.config.is_empty()


@pytest.mark.parametrize("content", [None, "", "{", "null", "[]", '{"schemaVersion":"1.0","completed":true}'])
def test_missing_and_malformed_results_fail_closed(entry: NL2ALEntry, workspace: Path, tmp_path: Path, content: str | None):
    def fake_run(args: list[str], **_: object):
        if content is not None:
            argument_path(args, "--result=").write_text(content, encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    expected_message = "missing or unreadable" if content is None else "malformed"
    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run), pytest.raises(BCalScenarioError, match=expected_message) as failure:
        invoke(entry, workspace, tmp_path / "results")

    assert failure.value.metrics.turn_count is None


@pytest.mark.parametrize("field", ["schemaVersion", "completed", "steps", "interactions", "toolUsage", "totals", "export", "sessionArchive", "failure"])
def test_missing_result_contract_fields_fail_closed(entry: NL2ALEntry, workspace: Path, tmp_path: Path, field: str):
    payload = native_result()
    del payload[field]

    def fake_run(args: list[str], **_: object):
        argument_path(args, "--result=").write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run), pytest.raises(BCalScenarioError, match="malformed"):
        invoke(entry, workspace, tmp_path / "results")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda result: result.update(schemaVersion="2.0"),
        lambda result: result.update(completed="true"),
        lambda result: result.update(steps=None),
        lambda result: result["steps"].append(None),
        lambda result: result.update(interactions={}),
        lambda result: result["export"].update(success=1),
        lambda result: result["totals"].update(steps="4"),
        lambda result: result["totals"].update(inputTokens=-1),
    ],
)
def test_result_contract_is_strictly_typed(entry: NL2ALEntry, workspace: Path, tmp_path: Path, mutate):
    payload = native_result()
    mutate(payload)

    def fake_run(args: list[str], **_: object):
        save_result(args, payload)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run), pytest.raises(BCalScenarioError, match="malformed"):
        invoke(entry, workspace, tmp_path / "results")


@pytest.mark.parametrize("action", ["cancel", "decline", "accept"])
def test_unexpected_clarification_cannot_become_success(entry: NL2ALEntry, workspace: Path, tmp_path: Path, action: str):
    payload = native_result()
    payload["interactions"] = [
        {
            "sequence": 1,
            "ruleId": "unexpected-clarification",
            "matched": True,
            "usedDefault": True,
            "request": {"question": "Which field?", "choices": ["Budget"], "allowFreeform": True, "inputType": "string", "isRequired": True},
            "match": {"default": True},
            "response": {"action": action, "value": "Budget" if action == "accept" else "", "selectedChoice": None, "selectedIndex": None},
            "failure": None,
        }
    ]

    def fake_run(args: list[str], **_: object):
        save_result(args, payload)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run), pytest.raises(BCalScenarioError, match="Unexpected clarification"):
        invoke(entry, workspace, tmp_path / "results")


def test_rejected_interaction_keeps_native_failure(entry: NL2ALEntry, workspace: Path, tmp_path: Path):
    payload = native_result()
    payload["interactions"] = [
        {
            "sequence": 1,
            "ruleId": None,
            "matched": False,
            "usedDefault": False,
            "request": {"question": "Continue?", "inputType": "string"},
            "match": None,
            "response": None,
            "failure": {"code": "unmatched_interaction", "message": "No matching interaction rule"},
        }
    ]

    def fake_run(args: list[str], **_: object):
        save_result(args, payload)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run), pytest.raises(BCalScenarioError, match="unmatched_interaction: No matching interaction rule"):
        invoke(entry, workspace, tmp_path / "results")


def test_nonzero_exit_preserves_failure_and_actual_attempted_turn_count(entry: NL2ALEntry, workspace: Path, tmp_path: Path):
    payload = native_result(("succeeded", "failed"))
    payload["completed"] = False
    payload["failure"] = payload["steps"][1]["failure"] = {"code": "model_failed", "message": "Backend unavailable", "stepId": "turn-2"}

    def fake_run(args: list[str], **_: object):
        save_result(args, payload)
        raise subprocess.CalledProcessError(2, args, output=b"native stdout", stderr=b"native stderr")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run), pytest.raises(BCalScenarioError, match="status 2") as failure:
        invoke(entry, workspace, tmp_path / "results")

    assert "model_failed (turn-2): Backend unavailable" in str(failure.value)
    assert "native stdout" in str(failure.value)
    assert "native stderr" in str(failure.value)
    assert failure.value.metrics.turn_count == 2
    assert failure.value.metrics.prompt_tokens == 200
    assert failure.value.metrics.completion_tokens == 80


def test_nonzero_exit_cannot_be_overridden_by_success_result(entry: NL2ALEntry, workspace: Path, tmp_path: Path):
    def fake_run(args: list[str], **_: object):
        save_result(args, native_result())
        raise subprocess.CalledProcessError(3, args)

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run), pytest.raises(BCalScenarioError, match="status 3") as failure:
        invoke(entry, workspace, tmp_path / "results")

    assert failure.value.metrics.turn_count == 4


def test_skipped_steps_are_not_counted_as_executed_turns(entry: NL2ALEntry, workspace: Path, tmp_path: Path):
    payload = native_result(("succeeded", "failed", "skipped", "skipped"))

    def fake_run(args: list[str], **_: object):
        save_result(args, payload)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run), pytest.raises(BCalScenarioError, match="status=skipped") as failure:
        invoke(entry, workspace, tmp_path / "results")

    assert failure.value.metrics.turn_count == 2


@pytest.mark.parametrize("has_partial_result", [False, True])
def test_timeout_uses_one_total_budget_and_preserves_available_metrics(entry: NL2ALEntry, workspace: Path, tmp_path: Path, has_partial_result: bool):
    def fake_run(args: list[str], **_: object):
        if has_partial_result:
            payload = native_result(("succeeded",))
            payload["completed"] = False
            payload["failure"] = {"code": "scenario_canceled", "message": "Scenario execution was canceled."}
            save_result(args, payload)
        raise subprocess.TimeoutExpired(args, bcal_agent._config.timeout.bcal_execution, output=b"partial \xff", stderr=b"timeout details")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run) as process, pytest.raises(AgentTimeoutError, match="timed out") as failure:
        invoke(entry, workspace, tmp_path / "results")

    process.assert_called_once()
    assert process.call_args.kwargs["timeout"] == bcal_agent._config.timeout.bcal_execution
    assert failure.value.metrics is not None
    assert failure.value.metrics.execution_time == bcal_agent._config.timeout.bcal_execution
    assert failure.value.metrics.turn_count == (1 if has_partial_result else None)
    assert failure.value.config is not None
    assert failure.value.config.is_empty()
    assert "partial \ufffd" in str(failure.value)
    assert "timeout details" in str(failure.value)
    result_path = argument_path(process.call_args.args[0], "--result=")
    assert result_path.with_name("stdout.log").read_text(encoding="utf-8") == "partial \ufffd"
    assert not result_path.is_relative_to(workspace)


def test_process_start_failure_is_an_agent_error(entry: NL2ALEntry, workspace: Path, tmp_path: Path):
    with patch.object(bcal_agent.subprocess, "run", side_effect=OSError("Cannot start bcal")), pytest.raises(BCalScenarioError, match="Cannot start bcal") as failure:
        invoke(entry, workspace, tmp_path / "results")

    assert failure.value.metrics.turn_count is None


def test_default_artifacts_are_in_explicit_workspace_sibling(entry: NL2ALEntry, workspace: Path):
    def fake_run(args: list[str], **_: object):
        save_result(args, native_result())
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run) as process:
        bcal_agent.run_bcal_agent(entry, workspace, BCalBackendConfig(command="python bridge.py"))

    result_path = argument_path(process.call_args.args[0], "--result=")
    assert result_path.parent.parent == workspace.with_name(f"{workspace.name}-bcal-artifacts")
    assert not result_path.is_relative_to(workspace)


def test_result_dir_can_be_parent_of_isolated_workspace(entry: NL2ALEntry, workspace: Path):
    def fake_run(args: list[str], **_: object):
        save_result(args, native_result())
        return subprocess.CompletedProcess(args, 0, stdout="Scenario completed", stderr="")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run) as process:
        invoke(entry, workspace, workspace.parent)

    result_path = argument_path(process.call_args.args[0], "--result=")
    assert result_path.parent.parent == workspace.parent / "bcal-scenario" / entry.instance_id
    assert not any(path.is_relative_to(workspace) for path in result_path.parent.iterdir())
    assert not any(path.is_file() for path in workspace.rglob("*"))


@pytest.mark.parametrize("nested", [False, True])
def test_artifacts_inside_generated_source_workspace_are_rejected(entry: NL2ALEntry, workspace: Path, nested: bool):
    result_dir = workspace / "results" if nested else workspace
    with patch.object(bcal_agent.subprocess, "run") as process, pytest.raises(AgentError, match="outside the generated-source workspace"):
        invoke(entry, workspace, result_dir)

    process.assert_not_called()
    assert not (result_dir / "bcal-scenario").exists()


def test_stale_success_cannot_mask_a_missing_result_on_rerun(entry: NL2ALEntry, workspace: Path, tmp_path: Path):
    results: list[Path] = []

    def fake_run(args: list[str], **_: object):
        results.append(argument_path(args, "--result="))
        if len(results) == 1:
            save_result(args, native_result())
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    with patch.object(bcal_agent.subprocess, "run", side_effect=fake_run):
        invoke(entry, workspace, tmp_path / "results")
        with pytest.raises(BCalScenarioError, match="missing or unreadable"):
            invoke(entry, workspace, tmp_path / "results")

    assert len(results) == 2
    assert results[0] != results[1]
    assert results[0].is_file()
    assert not results[1].exists()


def test_single_shot_ignores_scenario_artifact_directory(workspace: Path, tmp_path: Path, scenario_help):
    entry = create_nl2al_entry()
    with patch.object(bcal_agent.subprocess, "run", return_value=subprocess.CompletedProcess(["bcal"], 0)) as process:
        metrics, _ = invoke(entry, workspace, tmp_path / "results")

    process.assert_called_once()
    scenario_help.assert_not_called()
    args = process.call_args.args[0]
    assert f"--prompt={entry.nl_prompt}" in args
    assert not any(argument.startswith(("--scenario=", "--result=")) for argument in args)
    assert not (tmp_path / "results").exists()
    assert metrics is not None
    assert metrics.turn_count is None
