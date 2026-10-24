from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"


def _workflow_text(name: str) -> str:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    assert yaml.safe_load(text)
    return text


def _workflow(name: str):
    return yaml.safe_load(_workflow_text(name))


def _step(workflow: dict[Any, Any], job: str, name: str) -> dict[str, Any]:
    return next(step for step in workflow["jobs"][job]["steps"] if step.get("name") == name)


def test_bcal_dispatch_exposes_only_gold_and_challenge():
    workflow = _workflow("bcal-evaluation.yml")
    dataset = workflow[True]["workflow_dispatch"]["inputs"]["dataset"]

    assert dataset["default"] == "gold"
    assert dataset["options"] == ["gold", "challenge"]
    assert "multiturn" not in _workflow_text("bcal-evaluation.yml")


def test_bcal_run_identity_includes_selected_dataset():
    workflow = _workflow("bcal-evaluation.yml")

    assert "${{ inputs.dataset || 'gold' }}" in workflow["run-name"]
    assert (
        "${{ inputs.bcal-package-selection == 'experiment-pinned' && format('experiment@{0}', inputs.bcal-version) || inputs.bcal-package-selection == 'official-pinned' && format('official@{0}', inputs.bcal-version) || 'official/latest' }}"
        in workflow["run-name"]
    )
    assert workflow["concurrency"]["group"] == (
        "bcal-evaluation-${{ inputs.dataset || 'gold' }}-${{ inputs.cohort || 'all' }}-${{ inputs.bcal-package-selection || 'official-latest' }}-${{ inputs.bcal-version || 'latest' }}-${{ inputs.test-run && 'test' || 'full' }}-x${{ inputs.repeat-count || 1 }}"
    )
    assert workflow["jobs"]["get-entries"]["with"]["dataset"] == "${{ inputs.dataset || 'gold' }}"
    assert workflow["jobs"]["get-entries"]["with"]["cohort"] == "${{ inputs.cohort || '' }}"
    assert workflow["jobs"]["get-entries"]["with"]["repeat-count"] == "${{ inputs.repeat-count || 1 }}"


def test_bcal_package_selection_defaults_to_official_latest_and_derives_branch_provenance():
    workflow = _workflow("bcal-evaluation.yml")
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    validation = _step(workflow, "validate-bcal-package", "Validate and resolve BCal package selection")
    provenance = _step(workflow, "validate-bcal-package", "Verify experimental package provenance")

    assert inputs["bcal-package-selection"] == {
        "description": "BCAL package selection",
        "required": False,
        "default": "official-latest",
        "type": "choice",
        "options": ["official-latest", "official-pinned", "experiment-pinned"],
    }
    assert "bcal-package-channel" not in inputs
    assert "bcal-version-mode" not in inputs
    assert "bcal-branch" not in inputs
    assert "BCAL_TEST_FEED_URL" not in workflow["env"]
    assert validation["env"]["EXPERIMENT_FEED_URL"] == "${{ secrets.BCAL_TEST_FEED_URL }}"
    assert "pkgs.dev.azure.com" not in _workflow_text("bcal-evaluation.yml")
    assert 'channel="experiment"' in validation["run"]
    assert 'version_mode="pinned"' in validation["run"]
    assert 'echo "version-mode=$version_mode" >> "$GITHUB_OUTPUT"' in validation["run"]
    assert 'feed="DynamicsSMBTest@Local"' in validation["run"]
    assert provenance["if"] == "${{ steps.resolve.outputs.source == 'experiment' }}"
    assert ".\\scripts\\Resolve-BCalPackageProvenance.ps1" in provenance["run"]
    assert "-ExpectedBranch" not in provenance["run"]
    assert '-TestFeedUrl "$env:BCAL_TEST_FEED_URL"' in provenance["run"]
    assert workflow["jobs"]["validate-bcal-package"]["outputs"]["branch"] == "${{ steps.provenance.outputs.branch || steps.resolve.outputs.branch }}"


@pytest.mark.parametrize("workflow_name", ["get-entries.yml", "summarize-results.yml"])
def test_reusable_dataset_input_is_optional_for_existing_callers(workflow_name):
    inputs = _workflow(workflow_name)[True]["workflow_call"]["inputs"]

    assert inputs["dataset"]["required"] is False
    assert inputs["dataset"]["default"] == ""


def test_get_entries_threads_optional_dataset_without_eval():
    workflow = _workflow_text("get-entries.yml")

    assert 'cmd=(uv run bcbench dataset list --category "$EVALUATION_CATEGORY" --github-output entries)' in workflow
    assert 'cmd+=(--dataset "$NL2AL_DATASET")' in workflow
    assert 'cmd+=(--cohort "$EVALUATION_COHORT")' in workflow
    assert 'cmd+=(--repeat-count "$REPEAT_COUNT")' in workflow
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
    assert "bcal-package-selection" in workflow
    assert "bcal-version-mode" not in workflow
    assert "scenario" not in workflow.lower()


def test_summary_runs_after_non_cancelled_matrix_failures_with_exact_ids():
    job = _workflow("bcal-evaluation.yml")["jobs"]["summarize-results"]

    assert set(job["needs"]) == {"validate-bcal-package", "get-entries", "evaluate-with-bcal"}
    assert "always()" in job["if"]
    assert "!cancelled()" in job["if"]
    assert "needs.validate-bcal-package.result == 'success'" in job["if"]
    assert "needs.get-entries.result == 'success'" in job["if"]
    assert "needs.get-entries.outputs.entries != '[]'" in job["if"]
    assert job["with"]["expected-entries"] == "${{ needs.get-entries.outputs.entries }}"
    assert job["with"]["dataset"] == "${{ inputs.dataset || 'gold' }}"
    assert job["with"]["bcal-package-channel"] == "${{ needs.validate-bcal-package.outputs.source }}"
    assert job["with"]["bcal-package-branch"] == "${{ needs.validate-bcal-package.outputs.branch }}"
    assert job["with"]["bcal-package-feed"] == "${{ needs.validate-bcal-package.outputs.feed }}"
    assert job["strategy"]["matrix"]["repetition"] == "${{ fromJson(needs.get-entries.outputs.repetitions) }}"
    assert job["with"]["cohort-name"] == "${{ needs.get-entries.outputs.cohort-name }}"
    assert job["with"]["cohort-sha256"] == "${{ needs.get-entries.outputs.cohort-sha256 }}"
    assert job["with"]["repetition-index"] == "${{ matrix.repetition }}"
    assert job["with"]["repetition-count"] == "${{ fromJson(needs.get-entries.outputs.repetition-count) }}"


def test_bcal_repetitions_use_independent_result_artifacts_and_summaries():
    workflow = _workflow("bcal-evaluation.yml")
    evaluate_job = workflow["jobs"]["evaluate-with-bcal"]
    summary_job = workflow["jobs"]["summarize-results"]
    upload = _step(workflow, "evaluate-with-bcal", "Upload evaluation results")
    run = _step(workflow, "evaluate-with-bcal", "Run BCal for entry ${{ matrix.entry }}")

    assert evaluate_job["strategy"]["matrix"]["repetition"] == "${{ fromJson(needs.get-entries.outputs.repetitions) }}"
    assert "if ([int]$env:BCBENCH_REPETITION_COUNT -gt 1)" in run["run"]
    assert '$runId = "$runId-r$env:BCBENCH_REPETITION_INDEX"' in run["run"]
    assert '--run-id "$runId"' in run["run"]
    assert "format('-r{0}', matrix.repetition)" in upload["with"]["name"]
    assert "format('-r{0}', matrix.repetition)" in summary_job["with"]["artifact-pattern"]
    assert "format('{0}-r{1}', github.run_id, matrix.repetition)" in summary_job["with"]["evaluation-run-id"]


def test_summary_validates_coverage_and_tags_selected_dataset():
    workflow = _workflow_text("summarize-results.yml")

    assert "continue-on-error: ${{ inputs.expected-entries != '' }}" in workflow
    assert 'cmd+=(--dataset "$NL2AL_DATASET")' in workflow
    assert 'cmd+=(--expected-entries "$EXPECTED_ENTRIES")' in workflow
    assert "Upload evaluation coverage diagnostics" in workflow
    assert "if: always()" in workflow
    assert 'RUN_NAME="${RUN_NAME} [${NL2AL_DATASET}]"' in workflow
    assert 'RUN_TAGS="${RUN_TAGS},dataset-${NL2AL_DATASET}"' in workflow
    assert 'RUN_NAME="${RUN_NAME} [${BCAL_PACKAGE_CHANNEL}:${BCAL_PACKAGE_BRANCH}]"' in workflow
    assert "bcal-channel-${CHANNEL_TAG}" in workflow
    assert "bcal-branch-${PACKAGE_BRANCH_TAG}" in workflow
    assert "bcal-feed-${FEED_TAG}" in workflow
    assert '--run-id "$RESULT_RUN_ID"' in workflow
    assert "inputs.artifact-pattern" in workflow
    assert 'RUN_NAME="${RUN_NAME} [cohort:${COHORT_NAME}]"' in workflow
    assert 'RUN_NAME="${RUN_NAME} [repetition:${REPETITION_INDEX}/${REPETITION_COUNT}]"' in workflow
