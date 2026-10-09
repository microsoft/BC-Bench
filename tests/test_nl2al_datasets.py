import json
from hashlib import sha256
from unittest.mock import PropertyMock, patch

import pytest
import typer
from pydantic import ValidationError
from typer.testing import CliRunner

from bcbench.cli import app
from bcbench.commands.evaluate import evaluate_bcal
from bcbench.dataset import NL2ALEntry, NL2ALTurn
from bcbench.exceptions import AgentError
from bcbench.results.base import BaseEvaluationResult, JudgeBasedEvaluationResult
from bcbench.results.bceval_export import write_bceval_results
from bcbench.types import AgentHarness, EvaluationCategory, NL2ALDataset
from tests.conftest import create_evaluation_context, create_nl2al_entry


def write_entry(path, entry):
    path.write_text(entry.model_dump_json() + "\n", encoding="utf-8")


def result_for(entry, panel, path, tmp_path):
    context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.NL2AL, agent_name=AgentHarness.BCAL)
    context.dataset = panel
    context.dataset_version = panel.version
    context.dataset_sha256 = sha256(path.read_bytes()).hexdigest()
    context.agent_version = "18.0.1.2-beta"
    return context, JudgeBasedEvaluationResult.create_raw(context, "generated AL")


@pytest.mark.parametrize(("panel", "count"), [(NL2ALDataset.GOLD, 110), (NL2ALDataset.CHALLENGE, 65), (NL2ALDataset.MULTITURN, 7)])
def test_committed_panels_have_expected_counts_and_identity(panel, count):
    path = EvaluationCategory.NL2AL.dataset_path_for(panel)
    entries = NL2ALEntry.load(path)
    assert len(entries) == count
    assert len({entry.instance_id for entry in entries}) == count
    assert all(bool(entry.turns) == (panel is NL2ALDataset.MULTITURN) for entry in entries)
    manifest = json.loads(path.with_name("nl2al_manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == panel.version
    assert manifest["panels"][panel.value]["sha256"] == sha256(path.read_bytes()).hexdigest()
    assert all(entry.metadata.family and entry.metadata.tier for entry in entries)
    if panel is NL2ALDataset.MULTITURN:
        assert all(turn.intent == "customize" for entry in entries for turn in entry.turns)


def test_mixed_conversations_are_preserved_but_not_selected():
    base = EvaluationCategory.NL2AL.dataset_path
    pending = NL2ALEntry.load(base.with_name("nl2al_multiturn_pending.jsonl"))
    runnable = NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN))
    assert len(pending) == 7
    assert all(any(turn.intent != "customize" for turn in entry.turns) for entry in pending)
    assert not {entry.instance_id for entry in pending}.intersection(entry.instance_id for entry in runnable)


def test_panels_are_disjoint_and_only_publishable_inputs_are_committed():
    ids = set()
    for panel in NL2ALDataset:
        path = EvaluationCategory.NL2AL.dataset_path_for(panel)
        text = path.read_text(encoding="utf-8")
        assert "sharepoint.com/personal/" not in text
        assert "teams.microsoft.com/l/message/" not in text
        assert "C:\\\\Users\\\\" not in text
        assert '"source_refs"' not in text
        assert "BCAL_BENIGN_MARKER" not in text
        entries = NL2ALEntry.load(path)
        panel_ids = {entry.instance_id for entry in entries}
        assert not ids.intersection(panel_ids)
        ids.update(panel_ids)


def test_selector_rejected_for_other_category():
    with pytest.raises(ValueError, match="only supported"):
        EvaluationCategory.BUG_FIX.dataset_path_for(NL2ALDataset.CHALLENGE)


def test_multiturn_uses_last_customization_not_obsolete_checkpoints():
    entry = next(e for e in NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN)) if "continuity-note-undo" in e.instance_id)
    assert len(entry.turns) == 4
    assert "Note Reviewed" in entry.turns[2].prompt
    assert entry.expected == entry.turns[-1].expected
    assert any("removed" in check["text"] for check in entry.expected)
    assert "User turn 1" in entry.get_task()
    assert "User turn 4" in entry.get_task()
    assert entry.turns[0].prompt == entry.nl_prompt


def test_multiturn_rejects_missing_final_checkpoint_and_fake_first_prompt():
    entry = NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN))[0]
    data = entry.model_dump()
    data["expected"] = [{"text": "Wrong final state", "level": "critical"}]
    with pytest.raises(ValidationError, match="final customization"):
        NL2ALEntry.model_validate(data)
    data = entry.model_dump()
    data["nl_prompt"] = "Not the first user message"
    with pytest.raises(ValidationError, match="first actual"):
        NL2ALEntry.model_validate(data)
    with pytest.raises(ValidationError, match="Only customization"):
        NL2ALTurn(prompt="Inspect", intent="inspect", expected=entry.expected)


def test_cli_selects_challenge_for_listing_view_and_version(tmp_path, monkeypatch):
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    runner = CliRunner()
    entry = NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.CHALLENGE))[0]
    listed = runner.invoke(app, ["dataset", "list", "--category", "nl2al", "--dataset", "challenge"])
    assert listed.exit_code == 0, listed.output
    assert "65 entry" in listed.output
    assert entry.instance_id in listed.output
    viewed = runner.invoke(app, ["dataset", "view", entry.instance_id, "--category", "nl2al", "--dataset", "challenge"])
    assert viewed.exit_code == 0, viewed.output
    version = runner.invoke(app, ["dataset", "version", entry.instance_id, "--category", "nl2al", "--dataset", "challenge", "--github-output", "version"])
    assert version.exit_code == 0, version.output
    assert "version=28.0" in output.read_text(encoding="utf-8")
    assert "nl2al_challenge.jsonl" in output.read_text(encoding="utf-8")


@pytest.mark.parametrize("factory", ["create_raw", "create_agent_timeout_failure", "create_failure"])
def test_all_result_outcomes_preserve_dataset_identity(tmp_path, factory):
    entry = create_nl2al_entry()
    path = tmp_path / "nl2al_challenge.jsonl"
    write_entry(path, entry)
    context, _ = result_for(entry, NL2ALDataset.CHALLENGE, path, tmp_path)
    if factory == "create_raw":
        result = JudgeBasedEvaluationResult.create_raw(context, "AL")
    elif factory == "create_failure":
        result = JudgeBasedEvaluationResult.create_failure(context, "", "tool failed")
    else:
        result = JudgeBasedEvaluationResult.create_agent_timeout_failure(context)
    restored = BaseEvaluationResult.from_json(result.model_dump(mode="json"))
    assert restored.dataset is NL2ALDataset.CHALLENGE
    assert restored.dataset_sha256 == sha256(path.read_bytes()).hexdigest()
    assert restored.dataset_version == NL2ALDataset.CHALLENGE.version
    assert restored.agent_version == "18.0.1.2-beta"


def test_export_uses_selected_panel_assertions_and_kusto_metadata(tmp_path):
    gold = create_nl2al_entry(nl_prompt="Gold prompt")
    challenge = create_nl2al_entry(nl_prompt="Challenge prompt", expected=[{"text": "Challenge check", "level": "critical"}])
    write_entry(tmp_path / "nl2al.jsonl", gold)
    path = tmp_path / "nl2al_challenge.jsonl"
    write_entry(path, challenge)
    _, result = result_for(challenge, NL2ALDataset.CHALLENGE, path, tmp_path)
    result.model = "generation-model-a"
    result.judge_model = "checklist-model-b"
    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=tmp_path / "nl2al.jsonl"):
        write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL, dataset=NL2ALDataset.CHALLENGE)
    payload = json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))
    assert payload["input"] == "Challenge prompt"
    assert payload["expected"]["assertions"] == challenge.expected
    assert payload["metadata"]["dataset"] == "challenge"
    assert payload["metadata"]["dataset_sha256"] == result.dataset_sha256
    assert payload["metadata"]["dataset_version"] == NL2ALDataset.CHALLENGE.version
    assert payload["metadata"]["dataset_mode"] == "single_turn"
    assert payload["metadata"]["EvalRunType"] == "baseline"
    assert payload["metadata"]["agent_version"] == "18.0.1.2-beta"
    assert payload["metadata"]["model"] == "generation-model-a"
    assert payload["metadata"]["judge_model"] == "checklist-model-b"
    assert "dataset-challenge" in payload["tags"]


def test_export_rejects_wrong_panel_or_changed_assertions(tmp_path):
    entry = create_nl2al_entry()
    path = tmp_path / "nl2al_challenge.jsonl"
    write_entry(path, entry)
    _, result = result_for(entry, NL2ALDataset.CHALLENGE, path, tmp_path)
    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=tmp_path / "nl2al.jsonl"):
        with pytest.raises(ValueError, match="does not match selected"):
            write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL, dataset=NL2ALDataset.GOLD)
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="hash changed"):
            write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL, dataset=NL2ALDataset.CHALLENGE)


def test_export_does_not_guess_gold_identity_for_legacy_results(tmp_path):
    entry = create_nl2al_entry()
    path = tmp_path / "nl2al.jsonl"
    write_entry(path, entry)
    context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.NL2AL)
    result = JudgeBasedEvaluationResult.create_raw(context, "AL")
    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=path):
        write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL)
    row = json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))
    assert "dataset" not in row["metadata"]
    assert row["tags"] == []


def test_export_requires_recorded_identity_for_a_named_panel(tmp_path):
    entry = create_nl2al_entry()
    path = tmp_path / "nl2al_challenge.jsonl"
    write_entry(path, entry)
    _, result = result_for(entry, NL2ALDataset.CHALLENGE, path, tmp_path)
    result.dataset_sha256 = None
    with pytest.raises(ValueError, match="missing recorded"):
        write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL, dataset=NL2ALDataset.CHALLENGE)


def test_export_multiturn_marks_final_artifact_scope(tmp_path):
    path = EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.MULTITURN)
    entry = NL2ALEntry.load(path)[0]
    _, result = result_for(entry, NL2ALDataset.MULTITURN, path, tmp_path)
    write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL, dataset=NL2ALDataset.MULTITURN)
    row = json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))
    assert row["metadata"]["evaluation_scope"] == "final_artifact"
    assert row["metadata"]["dataset_turn_count"] == len(entry.turns)
    assert row["expected"] == entry.get_expected_output()


def test_evaluate_failure_keeps_panel_and_isolates_workspace(tmp_path):
    path = EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.CHALLENGE)
    entry = NL2ALEntry.load(path)[0]
    captured = {}

    def fail(context, _runner):
        captured["workspace"] = context.repo_path
        raise AgentError("scenario execution failed")

    with (
        patch("bcbench.evaluate.nl2al.NL2ALPipeline.execute", side_effect=fail),
        patch("bcbench.commands.evaluate.get_bcal_version", return_value="18.0.1.2-beta"),
        pytest.raises(typer.Exit) as error,
    ):
        evaluate_bcal(entry.instance_id, repo_path=tmp_path / "work", output_dir=tmp_path / "out", run_id="test", llm_command="bridge", dataset=NL2ALDataset.CHALLENGE)
    assert error.value.exit_code == 1
    assert captured["workspace"] == tmp_path / "work" / entry.instance_id / "workspace"
    result = json.loads((tmp_path / "out" / "test" / f"{entry.instance_id}.jsonl").read_text(encoding="utf-8"))
    assert result["dataset"] == "challenge"
    assert result["agent_version"] == "18.0.1.2-beta"
    assert result["error_message"] == "scenario execution failed"
