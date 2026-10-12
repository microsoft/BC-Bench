import json
from hashlib import sha256
from unittest.mock import PropertyMock, patch

import pytest
from typer.testing import CliRunner

from bcbench.cli import app
from bcbench.commands import evaluate as evaluate_commands
from bcbench.commands import run as run_commands
from bcbench.dataset import NL2ALEntry
from bcbench.dataset.dataset_entry import EntryMetadata
from bcbench.results.base import BaseEvaluationResult, JudgeBasedEvaluationResult
from bcbench.results.bceval_export import write_bceval_results
from bcbench.types import AgentHarness, EvaluationCategory, NL2ALDataset
from tests.conftest import create_evaluation_context, create_nl2al_entry


def _write_entry(path, entry):
    path.write_text(entry.model_dump_json() + "\n", encoding="utf-8")


def _panel_entry(panel: NL2ALDataset, *, prompt: str, expected=None) -> NL2ALEntry:
    entry = create_nl2al_entry(nl_prompt=prompt, expected=expected)
    return entry.model_copy(
        update={
            "metadata": EntryMetadata(area="customer", family="customer-industry", tier=panel.value),
            "language": "en-US",
        }
    )


def _result_for(entry: NL2ALEntry, panel: NL2ALDataset, path, tmp_path):
    context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.NL2AL, agent_name=AgentHarness.BCAL)
    context.dataset = panel
    context.dataset_version = panel.version
    context.dataset_sha256 = sha256(path.read_bytes()).hexdigest()
    return context, JudgeBasedEvaluationResult.create_raw(context, "generated AL")


@pytest.mark.parametrize(("panel", "count"), [(NL2ALDataset.GOLD, 110), (NL2ALDataset.CHALLENGE, 65)])
def test_committed_panels_have_reviewed_single_turn_identity(panel, count):
    path = EvaluationCategory.NL2AL.dataset_path_for(panel)
    entries = NL2ALEntry.load(path)
    manifest = json.loads(path.with_name("nl2al_manifest.json").read_text(encoding="utf-8"))

    assert list(NL2ALDataset) == [NL2ALDataset.GOLD, NL2ALDataset.CHALLENGE]
    assert len(entries) == count
    assert len({entry.instance_id for entry in entries}) == count
    assert manifest["version"] == panel.version
    assert manifest["panels"][panel.value]["count"] == count
    assert manifest["panels"][panel.value]["sha256"] == sha256(path.read_bytes()).hexdigest()
    assert manifest["panels"][panel.value]["evaluation_scope"] == "single_turn"
    assert all(entry.metadata.family for entry in entries)
    assert all(entry.metadata.tier == panel.value for entry in entries)
    assert all(entry.language for entry in entries)
    assert all(not hasattr(entry, "turns") for entry in entries)


def test_panel_selector_is_rejected_for_other_categories():
    with pytest.raises(ValueError, match="only supported"):
        EvaluationCategory.BUG_FIX.dataset_path_for(NL2ALDataset.CHALLENGE)


def test_cli_selects_challenge_for_listing_view_and_version(tmp_path, monkeypatch):
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    runner = CliRunner()
    entry = NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.CHALLENGE))[0]

    listed = runner.invoke(app, ["dataset", "list", "--category", "nl2al", "--dataset", "challenge"])
    viewed = runner.invoke(app, ["dataset", "view", entry.instance_id, "--category", "nl2al", "--dataset", "challenge"])
    version = runner.invoke(
        app,
        ["dataset", "version", entry.instance_id, "--category", "nl2al", "--dataset", "challenge", "--github-output", "version"],
    )

    assert listed.exit_code == 0, listed.output
    assert "Found 65 entry(ies)" in listed.output
    assert entry.instance_id in listed.output
    assert viewed.exit_code == 0, viewed.output
    assert entry.metadata.family is not None
    assert entry.metadata.family in viewed.output
    assert version.exit_code == 0, version.output
    outputs = output.read_text(encoding="utf-8")
    assert "version=28.0" in outputs
    assert "dataset-path=" in outputs
    assert "nl2al_challenge.jsonl" in outputs


def test_run_bcal_uses_selected_panel_without_changing_workspace_behavior(tmp_path):
    entry = NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.CHALLENGE))[0]
    captured = {}

    class Pipeline:
        def setup_workspace(self, selected_entry, repo_path):
            captured["entry"] = selected_entry
            captured["repo_path"] = repo_path

    with (
        patch.object(EvaluationCategory, "pipeline", new_callable=PropertyMock, return_value=Pipeline()),
        patch.object(run_commands, "run_bcal_agent") as run_agent,
    ):
        run_commands.run_bcal(entry.instance_id, repo_path=tmp_path, llm_command="bridge", dataset=NL2ALDataset.CHALLENGE)

    assert captured["entry"].instance_id == entry.instance_id
    assert captured["repo_path"] == tmp_path
    assert run_agent.call_args.kwargs["repo_path"] == tmp_path


def test_evaluate_bcal_persists_selected_panel_identity(tmp_path):
    path = EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.CHALLENGE)
    entry = NL2ALEntry.load(path)[0]
    captured = {}

    class Pipeline:
        def execute(self, context, _agent_runner):
            captured["context"] = context

    with (
        patch.object(EvaluationCategory, "pipeline", new_callable=PropertyMock, return_value=Pipeline()),
        patch.object(evaluate_commands, "get_bcal_version", return_value="18.0.1.2-beta"),
    ):
        evaluate_commands.evaluate_bcal(
            entry.instance_id,
            repo_path=tmp_path / "repo",
            output_dir=tmp_path / "results",
            run_id="run",
            llm_command="bridge",
            dataset=NL2ALDataset.CHALLENGE,
        )

    context = captured["context"]
    assert context.repo_path == tmp_path / "repo"
    assert context.dataset is NL2ALDataset.CHALLENGE
    assert context.dataset_version == NL2ALDataset.CHALLENGE.version
    assert context.dataset_sha256 == sha256(path.read_bytes()).hexdigest()
    assert context.agent_version == "18.0.1.2-beta"


@pytest.mark.parametrize("factory", ["raw", "timeout", "failure"])
def test_all_result_outcomes_preserve_dataset_identity(tmp_path, factory):
    entry = _panel_entry(NL2ALDataset.CHALLENGE, prompt="Challenge prompt")
    path = tmp_path / "nl2al_challenge.jsonl"
    _write_entry(path, entry)
    context, result = _result_for(entry, NL2ALDataset.CHALLENGE, path, tmp_path)

    if factory == "timeout":
        result = JudgeBasedEvaluationResult.create_agent_timeout_failure(context)
    elif factory == "failure":
        result = JudgeBasedEvaluationResult.create_failure(context, "", "tool failed")

    restored = BaseEvaluationResult.from_json(result.model_dump(mode="json"))
    assert restored.dataset is NL2ALDataset.CHALLENGE
    assert restored.dataset_version == NL2ALDataset.CHALLENGE.version
    assert restored.dataset_sha256 == sha256(path.read_bytes()).hexdigest()


def test_export_uses_selected_panel_assertions_and_provenance(tmp_path):
    gold = _panel_entry(NL2ALDataset.GOLD, prompt="Gold prompt")
    challenge = _panel_entry(
        NL2ALDataset.CHALLENGE,
        prompt="Challenge prompt",
        expected=[{"text": "Challenge check", "level": "critical"}],
    )
    _write_entry(tmp_path / "nl2al.jsonl", gold)
    challenge_path = tmp_path / "nl2al_challenge.jsonl"
    _write_entry(challenge_path, challenge)
    _, result = _result_for(challenge, NL2ALDataset.CHALLENGE, challenge_path, tmp_path)

    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=tmp_path / "nl2al.jsonl"):
        write_bceval_results(
            [result],
            tmp_path,
            "run",
            "export.jsonl",
            EvaluationCategory.NL2AL,
            dataset=NL2ALDataset.CHALLENGE,
        )

    payload = json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))
    assert payload["input"] == "Challenge prompt"
    assert payload["expected"]["assertions"] == challenge.expected
    assert payload["metadata"]["dataset"] == "challenge"
    assert payload["metadata"]["dataset_version"] == NL2ALDataset.CHALLENGE.version
    assert payload["metadata"]["dataset_sha256"] == result.dataset_sha256
    assert payload["metadata"]["dataset_mode"] == "single_turn"
    assert payload["metadata"]["dataset_turn_count"] == 1
    assert payload["metadata"]["evaluation_scope"] == "single_turn"
    assert payload["metadata"]["area"] == "customer"
    assert payload["metadata"]["family"] == "customer-industry"
    assert payload["metadata"]["scenario_tier"] == "challenge"
    assert {"dataset-challenge", "dataset-mode-single-turn", "evaluation-scope-single-turn", "tier-challenge"} <= set(payload["tags"])


def test_export_rejects_panel_hash_and_version_mismatches(tmp_path):
    entry = _panel_entry(NL2ALDataset.CHALLENGE, prompt="Challenge prompt")
    _write_entry(tmp_path / "nl2al.jsonl", _panel_entry(NL2ALDataset.GOLD, prompt="Gold prompt"))
    challenge_path = tmp_path / "nl2al_challenge.jsonl"
    _write_entry(challenge_path, entry)
    _, result = _result_for(entry, NL2ALDataset.CHALLENGE, challenge_path, tmp_path)

    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=tmp_path / "nl2al.jsonl"):
        with pytest.raises(ValueError, match="does not match selected"):
            write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL, dataset=NL2ALDataset.GOLD)

        challenge_path.write_text(challenge_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="hash changed"):
            write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL, dataset=NL2ALDataset.CHALLENGE)

        current_hash = sha256(challenge_path.read_bytes()).hexdigest()
        wrong_version = result.model_copy(update={"dataset_sha256": current_hash, "dataset_version": "wrong"})
        with pytest.raises(ValueError, match="version mismatch"):
            write_bceval_results([wrong_version], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL, dataset=NL2ALDataset.CHALLENGE)


def test_named_panel_requires_recorded_identity(tmp_path):
    entry = _panel_entry(NL2ALDataset.CHALLENGE, prompt="Challenge prompt")
    challenge_path = tmp_path / "nl2al_challenge.jsonl"
    _write_entry(challenge_path, entry)
    legacy_context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.NL2AL)
    legacy_result = JudgeBasedEvaluationResult.create_raw(legacy_context, "AL")

    with (
        patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=tmp_path / "nl2al.jsonl"),
        pytest.raises(ValueError, match="missing recorded dataset identity"),
    ):
        write_bceval_results(
            [legacy_result],
            tmp_path,
            "run",
            "export.jsonl",
            EvaluationCategory.NL2AL,
            dataset=NL2ALDataset.CHALLENGE,
        )


def test_legacy_export_does_not_guess_gold_identity(tmp_path):
    entry = create_nl2al_entry()
    gold_path = tmp_path / "nl2al.jsonl"
    _write_entry(gold_path, entry)
    context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.NL2AL)
    result = JudgeBasedEvaluationResult.create_raw(context, "AL")

    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=gold_path):
        write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL)

    payload = json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))
    assert "dataset" not in payload["metadata"]
    assert payload["tags"] == []
