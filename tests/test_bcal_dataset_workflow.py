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

    assert workflow["run-name"].startswith(f"BCal {SELECTED_TIER} ")
    assert (
        "${{ inputs.bcal-package-selection == 'experiment-pinned' && format('experiment@{0}', inputs.bcal-version) || inputs.bcal-package-selection == 'official-pinned' && format('official@{0}', inputs.bcal-version) || 'official/latest' }}"
        in workflow["run-name"]
    )
    assert workflow["concurrency"]["group"].startswith(f"bcal-evaluation-{SELECTED_TIER}-")


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
    assert 'feed="DynamicsSMBTest@Local"' in validation["run"]
    assert provenance["if"] == "${{ steps.resolve.outputs.source == 'experiment' }}"
    assert ".\\scripts\\Resolve-BCalPackageProvenance.ps1" in provenance["run"]
    assert "-ExpectedBranch" not in provenance["run"]
    assert '-TestFeedUrl "$env:BCAL_TEST_FEED_URL"' in provenance["run"]
    assert workflow["jobs"]["validate-bcal-package"]["outputs"]["branch"] == "${{ steps.provenance.outputs.branch || steps.resolve.outputs.branch }}"


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
    assert "${{ inputs." not in action_install["run"]


def test_summary_receives_package_provenance():
    job = _workflow("bcal-evaluation.yml")["jobs"]["summarize-results"]

    assert set(job["needs"]) == {"validate-bcal-package", "evaluate-with-bcal"}
    assert job["with"]["bcal-package-channel"] == "${{ needs.validate-bcal-package.outputs.source }}"
    assert job["with"]["bcal-package-branch"] == "${{ needs.validate-bcal-package.outputs.branch }}"
    assert job["with"]["bcal-package-feed"] == "${{ needs.validate-bcal-package.outputs.feed }}"


def test_summary_tags_package_provenance():
    workflow = _workflow_text("summarize-results.yml")

    assert 'RUN_NAME="${RUN_NAME} [${BCAL_PACKAGE_CHANNEL}:${BCAL_PACKAGE_BRANCH}]"' in workflow
    assert "bcal-channel-${CHANNEL_TAG}" in workflow
    assert "bcal-branch-${PACKAGE_BRANCH_TAG}" in workflow
    assert "bcal-feed-${FEED_TAG}" in workflow
