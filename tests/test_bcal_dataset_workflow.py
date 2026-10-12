from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"


def _workflow_text(name: str) -> str:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    assert yaml.safe_load(text)
    return text


def _workflow(name: str):
    return yaml.safe_load(_workflow_text(name))


def test_bcal_dispatch_exposes_only_gold_and_challenge():
    workflow = _workflow("bcal-evaluation.yml")
    dataset = workflow[True]["workflow_dispatch"]["inputs"]["dataset"]

    assert dataset["default"] == "gold"
    assert dataset["options"] == ["gold", "challenge"]
    assert "multiturn" not in _workflow_text("bcal-evaluation.yml")


def test_bcal_run_identity_includes_selected_dataset():
    workflow = _workflow_text("bcal-evaluation.yml")

    assert "run-name: BCal ${{ inputs.dataset || 'gold' }}" in workflow
    assert "group: bcal-evaluation-${{ inputs.dataset || 'gold' }}-" in workflow
    assert "dataset: ${{ inputs.dataset || 'gold' }}" in workflow


@pytest.mark.parametrize("workflow_name", ["get-entries.yml", "summarize-results.yml"])
def test_reusable_dataset_input_is_optional_for_existing_callers(workflow_name):
    inputs = _workflow(workflow_name)[True]["workflow_call"]["inputs"]

    assert inputs["dataset"]["required"] is False
    assert inputs["dataset"]["default"] == ""


def test_get_entries_threads_optional_dataset_without_eval():
    workflow = _workflow_text("get-entries.yml")

    assert 'cmd=(uv run bcbench dataset list --category "$EVALUATION_CATEGORY" --github-output entries)' in workflow
    assert 'cmd+=(--dataset "$NL2AL_DATASET")' in workflow
    assert '"${cmd[@]}"' in workflow
    assert 'eval "$cmd"' not in workflow
    assert workflow.index('if [[ "$MODIFIED_ONLY" == "true" ]]') < workflow.index('elif [[ "$TEST_RUN" == "true" ]]')


def test_bcal_resolves_symbols_and_evaluation_from_selected_panel():
    workflow = _workflow_text("bcal-evaluation.yml")

    assert 'dataset version "$env:INSTANCE_ID" --category nl2al --dataset "$env:NL2AL_DATASET"' in workflow
    assert "DATASET_PATH: ${{ steps.bcversion.outputs.dataset-path }}" in workflow
    assert '-DatasetPath "$env:DATASET_PATH"' in workflow
    assert 'evaluate bcal "$env:INSTANCE_ID" --dataset "$env:NL2AL_DATASET"' in workflow


def test_bcal_keeps_existing_installation_and_single_turn_execution():
    workflow = _workflow_text("bcal-evaluation.yml")

    assert ".github/actions/install-bcal" in workflow
    assert "bcal-version-mode" in workflow
    assert "scenario" not in workflow.lower()


def test_summary_runs_after_non_cancelled_matrix_failures_with_exact_ids():
    job = _workflow("bcal-evaluation.yml")["jobs"]["summarize-results"]

    assert set(job["needs"]) == {"get-entries", "evaluate-with-bcal"}
    assert "always()" in job["if"]
    assert "!cancelled()" in job["if"]
    assert "needs.get-entries.result == 'success'" in job["if"]
    assert "needs.get-entries.outputs.entries != '[]'" in job["if"]
    assert job["with"]["expected-entries"] == "${{ needs.get-entries.outputs.entries }}"
    assert job["with"]["dataset"] == "${{ inputs.dataset || 'gold' }}"


def test_summary_validates_coverage_and_tags_selected_dataset():
    workflow = _workflow_text("summarize-results.yml")

    assert "continue-on-error: ${{ inputs.expected-entries != '' }}" in workflow
    assert 'cmd+=(--dataset "$NL2AL_DATASET")' in workflow
    assert 'cmd+=(--expected-entries "$EXPECTED_ENTRIES")' in workflow
    assert "Upload evaluation coverage diagnostics" in workflow
    assert "if: always()" in workflow
    assert 'RUN_NAME="${RUN_NAME} [${NL2AL_DATASET}]"' in workflow
    assert 'RUN_TAGS="${RUN_TAGS},dataset-${NL2AL_DATASET}"' in workflow
