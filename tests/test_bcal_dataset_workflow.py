from pathlib import Path
from typing import Any

import yaml

from bcbench.types import DatasetTier

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"
SELECTED_TIER = "${{ inputs.tier || 'gold' }}"


def _workflow_text(name: str) -> str:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    assert yaml.safe_load(text)
    return text


def _workflow(name: str):
    return yaml.safe_load(_workflow_text(name))


def _step(workflow: dict[Any, Any], job: str, name: str) -> dict[str, Any]:
    return _step_named(workflow["jobs"][job]["steps"], name)


def _step_named(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(step for step in steps if step.get("name") == name)


def test_bcal_tier_choices_match_dataset_tiers():
    tier = _workflow("bcal-evaluation.yml")[True]["workflow_dispatch"]["inputs"]["tier"]

    assert tier["default"] == DatasetTier.GOLD
    assert tier["options"] == list(DatasetTier)


def test_bcal_threads_selected_tier_through_every_job():
    workflow = _workflow("bcal-evaluation.yml")
    text = _workflow_text("bcal-evaluation.yml")

    assert workflow["env"]["TIER"] == SELECTED_TIER
    assert workflow["jobs"]["get-entries"]["with"]["tier"] == SELECTED_TIER
    assert workflow["jobs"]["summarize-results"]["with"]["tier"] == SELECTED_TIER
    assert '--category nl2al --tier "$env:TIER" --github-output version' in text
    assert 'evaluate bcal "${{ matrix.entry }}" --tier "$env:TIER"' in text


def test_bcal_downloads_symbols_from_the_selected_tier():
    step = _step(_workflow("bcal-evaluation.yml"), "evaluate-with-bcal", "Download BC Application symbols")

    assert '-Category nl2al -Tier "$env:TIER"' in step["run"]


def test_bcal_run_identity_includes_tier_and_package_selection():
    workflow = _workflow("bcal-evaluation.yml")

    assert workflow["run-name"].startswith(
        f"BCal {SELECTED_TIER}${{{{ inputs.cohort && format('/{{0}}', inputs.cohort) || '' }}}} ${{{{ inputs.bcal-feed || 'official' }}}}@${{{{ inputs.bcal-version || 'latest' }}}} "
    )
    assert workflow["run-name"].endswith("${{ inputs.repeat-count > 1 && format(' x{0}', inputs.repeat-count) || '' }}")
    assert workflow["concurrency"]["group"] == "bcal-evaluation-${{ inputs.test-run && 'test' || 'full' }}"


def test_bcal_feed_selects_official_or_internal_test_feed():
    workflow = _workflow("bcal-evaluation.yml")
    feed = workflow[True]["workflow_dispatch"]["inputs"]["bcal-feed"]
    install = _step(workflow, "evaluate-with-bcal", "Install bcal CLI from internal feed")

    assert feed["default"] == "official"
    assert feed["options"] == ["official", "experiment"]
    assert install["with"]["feed"] == "${{ inputs.bcal-feed || 'official' }}"
    assert install["with"]["official-feed-url"] == "${{ secrets.BCAL_FEED_URL }}"
    assert install["with"]["experiment-feed-url"] == "${{ secrets.BCAL_TEST_FEED_URL }}"


def test_bcal_installs_selected_package():
    workflow = _workflow_text("bcal-evaluation.yml")
    install = _step(_workflow("bcal-evaluation.yml"), "evaluate-with-bcal", "Install bcal CLI from internal feed")
    action = yaml.safe_load((WORKFLOWS.parent / "actions" / "install-bcal" / "action.yml").read_text(encoding="utf-8"))
    action_install = _step_named(action["runs"]["steps"], "Install BCal package")

    assert install["uses"] == "$/.github/actions/install-bcal"
    assert install["with"]["version"] == "${{ env.BCAL_REQUESTED_VERSION }}"
    assert "bcal-version-mode" not in workflow
    assert '@("--version", $env:BCAL_REQUESTED_VERSION)' in action_install["run"]
    assert '@("--prerelease")' in action_install["run"]
    assert "--source $feedUrl" in action_install["run"]
    assert 'throw "No feed URL configured' in action_install["run"]
    assert "--add-source" not in action_install["run"]
    assert "${{ inputs." not in action_install["run"]


def test_experimental_feed_runs_are_published_as_experiments():
    job = _workflow("bcal-evaluation.yml")["jobs"]["summarize-results"]
    summarize = _workflow("summarize-results.yml")

    assert job["with"]["experiment"] == "${{ inputs.bcal-feed == 'experiment' }}"
    assert summarize[True]["workflow_call"]["inputs"]["experiment"]["default"] is False
    assert "${{ inputs.experiment && '--eval-run-type experiment' || '' }}" in _step(summarize, "summarize-results", "Upload result using bceval")["run"]


def test_bcal_threads_cohort_and_repetitions_into_entry_listing():
    workflow = _workflow("bcal-evaluation.yml")
    get_entries = _workflow("get-entries.yml")
    list_step = _step(get_entries, "get-entries", "Get entries for matrix")

    assert workflow["jobs"]["get-entries"]["with"]["cohort"] == "${{ inputs.cohort || '' }}"
    assert workflow["jobs"]["get-entries"]["with"]["repeat-count"] == "${{ format('{0}', inputs.repeat-count || 1) }}"
    assert get_entries[True]["workflow_call"]["inputs"]["repeat-count"]["type"] == "string"
    assert '--repeat-count \\"\\$REPEAT_COUNT\\"' in list_step["run"]
    assert 'cmd="$cmd --cohort \\"\\$EVALUATION_COHORT\\""' in list_step["run"]


def test_bcal_repetitions_use_independent_run_ids_artifacts_and_summaries():
    workflow = _workflow("bcal-evaluation.yml")
    evaluate_job = workflow["jobs"]["evaluate-with-bcal"]
    summary_job = workflow["jobs"]["summarize-results"]
    run = _step(workflow, "evaluate-with-bcal", "Run BCal for entry ${{ matrix.entry }}")
    upload = _step(workflow, "evaluate-with-bcal", "Upload evaluation results")
    repetition_suffix = "${{ inputs.repeat-count > 1 && format('-r{0}', matrix.repetition) || '' }}"

    assert evaluate_job["strategy"]["matrix"]["repetition"] == "${{ fromJson(needs.get-entries.outputs.repetitions) }}"
    assert summary_job["strategy"]["matrix"]["repetition"] == "${{ fromJson(needs.get-entries.outputs.repetitions) }}"
    assert run["env"]["RUN_ID_SUFFIX"] == repetition_suffix
    assert '--run-id "$env:GITHUB_RUN_ID$env:RUN_ID_SUFFIX"' in run["run"]
    assert repetition_suffix in upload["with"]["name"]
    assert summary_job["with"]["run-id-suffix"] == repetition_suffix


def test_bcal_records_cohort_and_repetition_metadata():
    workflow = _workflow("bcal-evaluation.yml")
    run = _step(workflow, "evaluate-with-bcal", "Run BCal for entry ${{ matrix.entry }}")
    summary = workflow["jobs"]["summarize-results"]["with"]

    assert run["env"]["BCBENCH_COHORT_NAME"] == "${{ needs.get-entries.outputs.cohort-name }}"
    assert run["env"]["BCBENCH_COHORT_SHA256"] == "${{ needs.get-entries.outputs.cohort-sha256 }}"
    assert "matrix.repetition" in run["env"]["BCBENCH_REPETITION_INDEX"]
    assert "needs.get-entries.outputs.repetition-count" in run["env"]["BCBENCH_REPETITION_COUNT"]
    assert "[cohort:{0}]" in summary["run-name-suffix"]
    assert "[repetition:{0}/{1}]" in summary["run-name-suffix"]
    assert "cohort-sha256-{1}" in summary["extra-tags"]
    assert "repetition-{0}-of-{1}" in summary["extra-tags"]


def test_summarize_results_isolates_repeated_runs():
    summarize = _workflow("summarize-results.yml")
    job = summarize["jobs"]["summarize-results"]
    text = _workflow_text("summarize-results.yml")

    assert job["env"]["RESULT_RUN_ID"] == "${{ github.run_id }}${{ inputs.run-id-suffix }}"
    assert '--run-id "$RESULT_RUN_ID"' in text
    assert "name: evaluation-summary${{ inputs.run-id-suffix }}" in text
    assert '--input-file "${{ inputs.results-dir }}/${RESULT_RUN_ID}/' in text
    assert "${{ github.run_id }}/" not in text
