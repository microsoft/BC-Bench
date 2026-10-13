import json
from hashlib import sha256
from unittest.mock import PropertyMock, patch

import pytest
import typer
from pydantic import ValidationError
from typer.testing import CliRunner

from bcbench.agent.bcal.scenario import BCalScenarioError
from bcbench.cli import app
from bcbench.commands import evaluate as evaluate_commands
from bcbench.commands import run as run_commands
from bcbench.dataset import NL2ALEntry, NL2ALTurn
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.bceval_export import write_bceval_results
from bcbench.types import AgentHarness, AgentMetrics, EvaluationCategory, NL2ALDataset
from tests.conftest import create_evaluation_context, create_nl2al_entry


def _write_entry(path, entry: NL2ALEntry) -> None:
    path.write_text(entry.model_dump_json() + "\n", encoding="utf-8")


def _result_for(entry: NL2ALEntry, panel: NL2ALDataset, path, tmp_path):
    context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.NL2AL, agent_name=AgentHarness.BCAL)
    context.dataset = panel
    context.dataset_version = panel.version
    context.dataset_sha256 = sha256(path.read_bytes()).hexdigest()
    return JudgeBasedEvaluationResult.create_raw(context, "generated AL")


def test_committed_multiturn_panel_has_reviewed_identity():
    path = EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN)
    entries = NL2ALEntry.load(path)
    manifest = json.loads(path.with_name("nl2al_manifest.json").read_text(encoding="utf-8"))

    assert len(entries) == 7
    assert len({entry.instance_id for entry in entries}) == 7
    assert manifest["version"] == NL2ALDataset.MULTITURN.version
    assert manifest["panels"]["multiturn"]["count"] == 7
    assert manifest["panels"]["multiturn"]["sha256"] == sha256(path.read_bytes()).hexdigest()
    assert manifest["panels"]["multiturn"]["evaluation_scope"] == "final_artifact"
    assert all(entry.metadata.family for entry in entries)
    assert all(entry.metadata.tier in ("gold", "challenge") for entry in entries)
    assert all(len(entry.turns) >= 2 for entry in entries)
    assert all(turn.intent == "customize" for entry in entries for turn in entry.turns)
    assert all(entry.turns[0].prompt == entry.nl_prompt for entry in entries)
    assert all(entry.expected == entry.turns[-1].expected for entry in entries)


def test_single_turn_panels_remain_single_turn():
    for panel in (NL2ALDataset.GOLD, NL2ALDataset.CHALLENGE):
        entries = NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(panel))
        assert all(not entry.turns for entry in entries)


def test_deferred_conversations_are_preserved_but_not_selectable():
    base = EvaluationCategory.NL2AL.dataset_path
    pending = NL2ALEntry.load(base.with_name("nl2al_multiturn_pending.jsonl"))
    runnable = NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN))

    assert len(pending) == 7
    assert all(any(turn.intent != "customize" for turn in entry.turns) for entry in pending)
    assert not {entry.instance_id for entry in pending}.intersection(entry.instance_id for entry in runnable)


def test_multiturn_task_preserves_authored_order_and_final_checkpoint():
    entry = next(entry for entry in NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN)) if "continuity-note-undo" in entry.instance_id)

    assert len(entry.turns) == 4
    assert entry.turns[0].prompt == entry.nl_prompt
    assert entry.expected == entry.turns[-1].expected
    assert "Note Reviewed" in entry.turns[2].prompt
    assert any("removed" in assertion["text"] for assertion in entry.expected)
    task = entry.get_task()
    assert task.index("User turn 1 (customize)") < task.index("User turn 4 (customize)")
    assert entry.turns[0].prompt in task
    assert entry.turns[-1].prompt in task


def test_multiturn_entry_validation_rejects_invalid_turn_structure():
    source = NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN))[0]

    data = source.model_dump()
    data["turns"] = data["turns"][:1]
    data["expected"] = data["turns"][0]["expected"]
    with pytest.raises(ValidationError, match="at least two"):
        NL2ALEntry.model_validate(data)

    data = source.model_dump()
    data["nl_prompt"] = "Not the first user message"
    with pytest.raises(ValidationError, match="first actual user turn"):
        NL2ALEntry.model_validate(data)

    data = source.model_dump()
    data["expected"] = [{"text": "Wrong final state", "level": "critical"}]
    with pytest.raises(ValidationError, match="final customization checkpoint"):
        NL2ALEntry.model_validate(data)

    data = source.model_dump()
    data["turns"] = [
        {"prompt": "Plan only", "intent": "plan", "expected": []},
        {"prompt": "Inspect only", "intent": "inspect", "expected": []},
    ]
    data["nl_prompt"] = "Plan only"
    with pytest.raises(ValidationError, match="final customization checkpoint"):
        NL2ALEntry.model_validate(data)


@pytest.mark.parametrize(
    ("intent", "expected"),
    [
        ("inspect", [{"text": "Artifact check", "level": "critical"}]),
        ("customize", []),
    ],
)
def test_turn_validation_restricts_artifact_expectations(intent, expected):
    with pytest.raises(ValidationError, match="Only customization turns"):
        NL2ALTurn(prompt="Turn", intent=intent, expected=expected)


def test_cli_selects_multiturn_for_listing_view_and_version(tmp_path, monkeypatch):
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    runner = CliRunner()
    entry = NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN))[0]

    listed = runner.invoke(app, ["dataset", "list", "--category", "nl2al", "--dataset", "multiturn"])
    viewed = runner.invoke(app, ["dataset", "view", entry.instance_id, "--category", "nl2al", "--dataset", "multiturn"])
    version = runner.invoke(
        app,
        ["dataset", "version", entry.instance_id, "--category", "nl2al", "--dataset", "multiturn", "--github-output", "version"],
    )

    assert listed.exit_code == 0, listed.output
    assert "Found 7 entry(ies)" in listed.output
    assert entry.instance_id in listed.output
    assert viewed.exit_code == 0, viewed.output
    assert "User turn 1 (customize)" in viewed.output
    assert version.exit_code == 0, version.output
    outputs = output.read_text(encoding="utf-8")
    assert "version=28.0" in outputs
    assert "nl2al_multiturn.jsonl" in outputs


def test_cli_test_run_validates_the_complete_multiturn_panel(tmp_path):
    source = NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN))[0]
    valid_entries = [source.model_copy(update={"instance_id": f"nl2al__valid-{index}"}) for index in range(5)]
    invalid_entry = create_nl2al_entry(instance_id="nl2al__single-row-in-multiturn-1")
    path = tmp_path / "nl2al_multiturn.jsonl"
    path.write_text("\n".join(entry.model_dump_json() for entry in [*valid_entries, invalid_entry]) + "\n", encoding="utf-8")

    with (
        patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=tmp_path / "nl2al.jsonl"),
        patch("random.sample", return_value=valid_entries[:4]),
    ):
        result = CliRunner().invoke(app, ["dataset", "list", "--category", "nl2al", "--dataset", "multiturn", "--test-run"])

    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    assert "turn structure" in str(result.exception)


def test_run_and_evaluate_reject_turn_structure_panel_mismatch(tmp_path):
    entry = create_nl2al_entry()
    _write_entry(tmp_path / "nl2al_multiturn.jsonl", entry)

    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=tmp_path / "nl2al.jsonl"):
        with pytest.raises(typer.BadParameter, match="turn structure"):
            run_commands.run_bcal(entry.instance_id, repo_path=tmp_path / "run", llm_command="bridge", dataset=NL2ALDataset.MULTITURN)
        with pytest.raises(typer.BadParameter, match="turn structure"):
            evaluate_commands.evaluate_bcal(
                entry.instance_id,
                repo_path=tmp_path / "work",
                output_dir=tmp_path / "out",
                run_id="run",
                llm_command="bridge",
                dataset=NL2ALDataset.MULTITURN,
            )


def test_export_multiturn_uses_authored_turns_and_final_artifact_scope(tmp_path):
    path = EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN)
    entry = NL2ALEntry.load(path)[0]
    result = _result_for(entry, NL2ALDataset.MULTITURN, path, tmp_path)

    write_bceval_results(
        [result],
        tmp_path,
        "run",
        "export.jsonl",
        EvaluationCategory.NL2AL,
        dataset=NL2ALDataset.MULTITURN,
    )

    row = json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))
    assert row["input"] == entry.get_task()
    assert row["expected"] == entry.get_expected_output()
    assert row["metadata"]["dataset"] == "multiturn"
    assert row["metadata"]["dataset_mode"] == "multiturn"
    assert row["metadata"]["dataset_turn_count"] == len(entry.turns)
    assert row["metadata"]["evaluation_scope"] == "final_artifact"
    assert {"dataset-multiturn", "dataset-mode-multiturn", "evaluation-scope-final-artifact"} <= set(row["tags"])


def test_export_rejects_single_turn_row_in_multiturn_panel(tmp_path):
    entry = create_nl2al_entry()
    _write_entry(tmp_path / "nl2al.jsonl", create_nl2al_entry(nl_prompt="Gold prompt"))
    path = tmp_path / "nl2al_multiturn.jsonl"
    _write_entry(path, entry)
    result = _result_for(entry, NL2ALDataset.MULTITURN, path, tmp_path)

    with (
        patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=tmp_path / "nl2al.jsonl"),
        pytest.raises(ValueError, match="turn structure"),
    ):
        write_bceval_results(
            [result],
            tmp_path,
            "run",
            "export.jsonl",
            EvaluationCategory.NL2AL,
            dataset=NL2ALDataset.MULTITURN,
        )


def test_export_rejects_mixed_multiturn_panel_even_when_selected_result_is_valid(tmp_path):
    valid = NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN))[0]
    single = create_nl2al_entry(instance_id="nl2al__single-row-in-multiturn-1")
    _write_entry(tmp_path / "nl2al.jsonl", create_nl2al_entry(nl_prompt="Gold prompt"))
    path = tmp_path / "nl2al_multiturn.jsonl"
    path.write_text(f"{valid.model_dump_json()}\n{single.model_dump_json()}\n", encoding="utf-8")
    result = _result_for(valid, NL2ALDataset.MULTITURN, path, tmp_path)

    with (
        patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=tmp_path / "nl2al.jsonl"),
        pytest.raises(ValueError, match="turn structure"),
    ):
        write_bceval_results(
            [result],
            tmp_path,
            "run",
            "export.jsonl",
            EvaluationCategory.NL2AL,
            dataset=NL2ALDataset.MULTITURN,
        )


def test_evaluate_passes_isolated_workspace_and_result_dir_to_agent(tmp_path):
    path = EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN)
    entry = NL2ALEntry.load(path)[0]
    captured = {}

    class Pipeline:
        def execute(self, context, agent_runner):
            captured["context"] = context
            agent_runner(context)

    with (
        patch.object(EvaluationCategory, "pipeline", new_callable=PropertyMock, return_value=Pipeline()),
        patch.object(evaluate_commands, "get_bcal_version", return_value="18.0.1.2-beta"),
        patch.object(evaluate_commands, "run_bcal_agent", return_value=(AgentMetrics(execution_time=1), None)) as run_agent,
    ):
        evaluate_commands.evaluate_bcal(
            entry.instance_id,
            repo_path=tmp_path / "work",
            output_dir=tmp_path / "out",
            run_id="run",
            llm_command="bridge",
            dataset=NL2ALDataset.MULTITURN,
        )

    context = captured["context"]
    assert context.repo_path == tmp_path / "work" / entry.instance_id / "workspace"
    assert context.result_dir == tmp_path / "out" / "run"
    assert context.agent_version == "18.0.1.2-beta"
    assert run_agent.call_args.kwargs["repo_path"] == context.repo_path
    assert run_agent.call_args.kwargs["result_dir"] == context.result_dir


def test_evaluate_saves_scenario_failure_with_metrics_and_dataset_identity(tmp_path):
    path = EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN)
    entry = NL2ALEntry.load(path)[0]
    captured = {}

    class Pipeline:
        def execute(self, context, _agent_runner):
            captured["context"] = context
            raise BCalScenarioError(
                "native scenario failed",
                AgentMetrics(execution_time=12, turn_count=2, prompt_tokens=300, completion_tokens=90, tool_usage={"compile": 2}),
            )

        def save_result(self, context, result):
            result.save(context.result_dir, f"{context.entry.instance_id}.jsonl")

    with (
        patch.object(EvaluationCategory, "pipeline", new_callable=PropertyMock, return_value=Pipeline()),
        patch.object(evaluate_commands, "get_bcal_version", return_value="18.0.1.2-beta"),
        pytest.raises(typer.Exit) as failure,
    ):
        evaluate_commands.evaluate_bcal(
            entry.instance_id,
            repo_path=tmp_path / "work",
            output_dir=tmp_path / "out",
            run_id="run",
            llm_command="bridge",
            dataset=NL2ALDataset.MULTITURN,
        )

    assert failure.value.exit_code == 1
    context = captured["context"]
    assert context.metrics is not None
    assert context.metrics.turn_count == 2
    assert context.experiment is not None
    assert context.experiment.is_empty()
    result = json.loads((tmp_path / "out" / "run" / f"{entry.instance_id}.jsonl").read_text(encoding="utf-8"))
    assert result["dataset"] == "multiturn"
    assert result["dataset_version"] == NL2ALDataset.MULTITURN.version
    assert result["dataset_sha256"] == sha256(path.read_bytes()).hexdigest()
    assert result["agent_version"] == "18.0.1.2-beta"
    assert result["metrics"]["turn_count"] == 2
    assert result["metrics"]["prompt_tokens"] == 300
    assert result["metrics"]["completion_tokens"] == 90
    assert result["error_message"] == "native scenario failed"
