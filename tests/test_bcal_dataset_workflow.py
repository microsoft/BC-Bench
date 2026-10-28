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

    run_name = workflow["run-name"]
    assert f"BCal {SELECTED_TIER}" in run_name
    assert "inputs.publish-source-run-id" in run_name
    assert "${{ inputs.bcal-feed || 'official' }}@${{ inputs.bcal-version || 'latest' }}" in run_name
    concurrency = workflow["concurrency"]["group"]
    for identity in (
        "inputs.tier",
        "inputs.cohort",
        "inputs.bcal-feed",
        "inputs.bcal-version",
        "inputs.study-id",
        "inputs.variant-id",
        "inputs.bcal-common-base-sha",
        "inputs.bcal-variant-patch-sha",
        "inputs.repeat-count",
    ):
        assert identity in concurrency


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


def test_bcal_study_inputs_are_validated_and_propagated():
    workflow = _workflow("bcal-evaluation.yml")
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    run_step = _step(workflow, "evaluate-with-bcal", "Run BCal for entry ${{ matrix.entry }}")
    validation = _step(workflow, "validate-study", "Validate study provenance")

    assert {"study-id", "variant-id", "bcal-common-base-sha", "bcal-variant-patch-sha", "cohort", "repeat-count"} <= inputs.keys()
    assert "must be nonempty together" in validation["run"]
    assert run_step["env"]["BCBENCH_STUDY_ID"] == "${{ inputs.study-id }}"
    assert run_step["env"]["BCBENCH_VARIANT_ID"] == "${{ inputs.variant-id }}"
    assert run_step["env"]["BCAL_COMMON_BASE_SHA"] == "${{ inputs.bcal-common-base-sha }}"
    assert run_step["env"]["BCAL_VARIANT_PATCH_SHA"] == "${{ inputs.bcal-variant-patch-sha }}"


def test_bcal_cohort_and_repetition_contract_reaches_matrix_and_results():
    workflow = _workflow("bcal-evaluation.yml")
    get_entries = workflow["jobs"]["get-entries"]["with"]
    evaluate = workflow["jobs"]["evaluate-with-bcal"]
    run_step = _step(workflow, "evaluate-with-bcal", "Run BCal for entry ${{ matrix.entry }}")

    assert get_entries["cohort"] == "${{ inputs.cohort || '' }}"
    assert "inputs.repeat-count" in get_entries["repeat-count"]
    assert evaluate["strategy"]["matrix"]["repetition"] == "${{ fromJson(needs.get-entries.outputs.repetitions) }}"
    assert run_step["env"]["BCBENCH_COHORT_NAME"] == "${{ needs.get-entries.outputs.cohort-name }}"
    assert run_step["env"]["BCBENCH_REPETITION_INDEX"] == "${{ (inputs.cohort != '' || inputs.repeat-count > 1) && matrix.repetition || '' }}"
