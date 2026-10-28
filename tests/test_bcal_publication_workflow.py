from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"


def _workflow(name: str) -> dict[Any, Any]:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _step(workflow: dict[Any, Any], job: str, name: str) -> dict[str, Any]:
    return next(step for step in workflow["jobs"][job]["steps"] if step.get("name") == name)


def test_normal_bcal_publication_runs_once_per_repetition_after_evaluation_failures():
    workflow = _workflow("bcal-evaluation.yml")
    summary = workflow["jobs"]["summarize-results"]

    assert summary["needs"] == ["validate-study", "get-entries", "evaluate-with-bcal"]
    assert "always()" in summary["if"]
    assert "!cancelled()" in summary["if"]
    assert "needs.validate-study.result == 'success'" in summary["if"]
    assert "needs.get-entries.result == 'success'" in summary["if"]
    assert summary["strategy"]["matrix"]["repetition"] == "${{ fromJson(needs.get-entries.outputs.repetitions) }}"
    assert summary["with"]["artifact-pattern"] == "evaluation-results-${{ github.run_id }}${{ (inputs.cohort != '' || inputs.repeat-count > 1) && format('-r{0}', matrix.repetition) || '' }}-*"
    assert summary["with"]["evaluation-run-id"] == "${{ (inputs.cohort != '' || inputs.repeat-count > 1) && format('{0}-r{1}', github.run_id, matrix.repetition) || github.run_id }}"
    assert summary["with"]["expected-entries"] == "${{ needs.get-entries.outputs.entries }}"
    assert summary["with"]["repetition-index"] == "${{ format('{0}', matrix.repetition) }}"
    assert summary["with"]["study-id"] == "${{ inputs.study-id }}"


def test_summary_can_download_one_repetition_from_a_prior_workflow_run():
    workflow = _workflow("summarize-results.yml")
    inputs = workflow[True]["workflow_call"]["inputs"]
    source = _step(workflow, "summarize-results", "Resolve source workflow metadata")
    download = _step(workflow, "summarize-results", "Download all evaluation results")
    summarize = _step(workflow, "summarize-results", "Summarize evaluation results")

    assert {"artifact-pattern", "source-workflow-run-id", "expected-entries", "evaluation-run-id", "cohort-name", "repetition-index", "study-id"} <= inputs.keys()
    assert download["with"]["pattern"] == "${{ inputs.artifact-pattern || '*' }}"
    assert download["with"]["run-id"] == "${{ inputs.source-workflow-run-id || github.run_id }}"
    assert download["with"]["github-token"] == "${{ secrets.GITHUB_TOKEN }}"
    assert "actions/runs/${SOURCE_WORKFLOW_RUN_ID}" in source["run"]
    assert '--source "${{ steps.source.outputs.head-sha }}"' in _step(workflow, "summarize-results", "Upload result using bceval")["run"]
    assert '--run-id "$RESULT_RUN_ID"' in summarize["run"]
    assert '--expected-entries "$EXPECTED_ENTRIES"' in summarize["run"]
    assert "--allow-incomplete-results" in summarize["run"]


def test_publication_recovery_has_no_evaluation_or_bcal_execution_jobs():
    workflow = _workflow("bcal-publish-existing-results.yml")
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    jobs = workflow["jobs"]
    publish = jobs["publish-results"]

    assert {"source-run-id", "tier", "cohort", "model", "bcal-feed", "bcal-version", "study-id", "variant-id", "bcal-common-base-sha", "bcal-variant-patch-sha", "repeat-count"} <= inputs.keys()
    assert set(jobs) == {"get-entries", "publish-results"}
    assert publish["strategy"]["matrix"]["repetition"] == "${{ fromJson(needs.get-entries.outputs.repetitions) }}"
    assert publish["with"]["artifact-pattern"] == "evaluation-results-${{ inputs.source-run-id }}-r${{ matrix.repetition }}-*"
    assert publish["with"]["source-workflow-run-id"] == "${{ inputs.source-run-id }}"
    assert publish["with"]["evaluation-run-id"] == "${{ inputs.source-run-id }}-r${{ matrix.repetition }}"
    assert publish["with"]["allow-incomplete-results"] is True
    assert "evaluate" not in str(workflow).lower()
    assert "install-bcal" not in str(workflow).lower()
