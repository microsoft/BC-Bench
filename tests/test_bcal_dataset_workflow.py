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

    assert workflow["run-name"].startswith(f"BCal {SELECTED_TIER} ${{{{ inputs.bcal-feed || 'official' }}}}@${{{{ inputs.bcal-version || 'latest' }}}} ")
    assert workflow["concurrency"]["group"] == "bcal-evaluation-${{ inputs.test-run && 'test' || 'full' }}"


def test_bcal_feed_selects_official_or_internal_test_feed():
    workflow = _workflow("bcal-evaluation.yml")
    feed = workflow[True]["workflow_dispatch"]["inputs"]["bcal-feed"]
    install = _step(workflow, "evaluate-with-bcal", "Install bcal CLI from internal feed")

    assert feed["default"] == "official"
    assert feed["options"] == ["official", "experiment"]
    assert install["with"]["feed-url"] == "${{ inputs.bcal-feed == 'experiment' && secrets.BCAL_TEST_FEED_URL || secrets.BCAL_FEED_URL }}"


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


def test_experimental_feed_runs_are_published_as_experiments():
    job = _workflow("bcal-evaluation.yml")["jobs"]["summarize-results"]
    summarize = _workflow("summarize-results.yml")

    assert job["with"]["experiment"] == "${{ inputs.bcal-feed == 'experiment' }}"
    assert summarize[True]["workflow_call"]["inputs"]["experiment"]["default"] is False
    assert "${{ inputs.experiment && '--eval-run-type experiment' || '' }}" in _step(summarize, "summarize-results", "Upload result using bceval")["run"]
