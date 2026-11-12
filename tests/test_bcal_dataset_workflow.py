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
    assert "format('bcal-evaluation-{0}', inputs.test-run && 'test' || 'full')" in workflow["concurrency"]["group"]
    assert "bcal-sdk-governed-policy-20261112-entry" in workflow["concurrency"]["group"]


def test_bcal_completion_review_model_offers_external_models_or_none():
    workflow = _workflow("bcal-evaluation.yml")
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    review_model = inputs["completion-review-model"]
    run = _step(workflow, "evaluate-with-bcal", "Run BCal for entry ${{ matrix.entry }}")

    assert review_model["default"] == "none"
    assert review_model["options"] == ["none", *inputs["external-model"]["options"]]
    assert run["env"]["BCAL_COMPLETION_REVIEW_MODEL"] == "${{ inputs.completion-review-model != 'none' && inputs.completion-review-model || '' }}"


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

    assert install["uses"] == "./.github/actions/install-bcal"
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

    assert job["with"]["experiment"] == "${{ inputs.bcal-feed == 'experiment' || inputs.agent-runtime == 'copilot-sdk' }}"
    assert summarize[True]["workflow_call"]["inputs"]["experiment"]["default"] is False
    assert "${{ inputs.experiment && '--eval-run-type experiment' || '' }}" in _step(summarize, "summarize-results", "Upload result using bceval")["run"]


def test_sdk_runtime_is_opt_in_and_requires_exact_package():
    workflow = _workflow("bcal-evaluation.yml")
    runtime = workflow[True]["workflow_dispatch"]["inputs"]["agent-runtime"]
    assert runtime["default"] == "legacy"
    assert runtime["options"] == ["legacy", "copilot-sdk"]
    assert workflow["env"]["BCAL_AGENT_RUNTIME"] == "${{ inputs.agent-runtime || 'legacy' }}"
    guard = _step(workflow, "evaluate-with-bcal", "Validate explicit SDK package selection")
    assert guard["if"] == "inputs.agent-runtime == 'copilot-sdk'"
    assert "BCAL_REQUESTED_VERSION -notmatch" in guard["run"]
    assert "requires an exact SDK-enabled" in guard["run"]
    assert "SDK_SMOKE_RUN" in guard["run"]
    assert "full-dataset SDK runs are not enabled" in guard["run"]
    assert workflow["jobs"]["evaluate-with-bcal"]["strategy"]["max-parallel"] == "${{ inputs.agent-runtime == 'copilot-sdk' && 4 || 32 }}"
    assert workflow["jobs"]["get-entries"]["with"]["test-run"] == "${{ inputs.agent-runtime == 'copilot-sdk' || inputs.test-run || false }}"


def test_sdk_provider_is_owned_authenticated_and_separate_from_auxiliary():
    workflow = _workflow("bcal-evaluation.yml")
    step = _step(workflow, "evaluate-with-bcal", "Run BCal for entry ${{ matrix.entry }}")
    script = step["run"]
    assert script.count("$proxy = Start-Process") == 1
    assert 'if ($env:BCAL_AGENT_RUNTIME -eq "copilot-sdk")' in script
    assert '"--wire-api", "responses"' in script
    assert "RandomNumberGenerator" in script
    assert 'BCAL_SDK_API_KEY_ENV = "BCAL_SDK_PROXY_KEY"' in script
    assert "Invoke-RestMethod" in script
    assert "finally {" in script
    assert "Stop-Process -Id $proxy.Id" in script
    assert "bc_eval_llm_api_bridge.py" in script
    assert step["env"]["BCAL_LLM_WIRE_API"] == "chat-completions"
    assert step["env"]["LLM_API_ENVIRONMENT"] == "TEST"
    assert "gh auth" not in script


def test_planning_policy_is_selected_explicitly_without_changing_legacy_schedule():
    workflow = _workflow("bcal-evaluation.yml")
    planning = workflow[True]["workflow_dispatch"]["inputs"]["agent-planning"]
    assert planning["default"] == "runtime-default"
    assert planning["options"] == ["runtime-default", "copilot", "bcal"]
    assert "BCAL_AGENT_PLANNING" not in workflow["env"]
    guard = _step(workflow, "evaluate-with-bcal", "Validate planning selection")["run"]
    assert 'BCAL_AGENT_RUNTIME -eq "legacy"' in guard
    assert 'REQUESTED_AGENT_PLANNING -eq "copilot"' in guard
    run = _step(workflow, "evaluate-with-bcal", "Run BCal for entry ${{ matrix.entry }}")["run"]
    assert 'if ($env:REQUESTED_AGENT_PLANNING -ne "runtime-default")' in run
    assert '@("--agent-planning", $env:REQUESTED_AGENT_PLANNING)' in run
    assert "@planningArgs" in run
    assert "inputs.agent-planning" in workflow["jobs"]["summarize-results"]["with"]["agent"]


def test_diagnostics_upload_on_failure_never_includes_private_credentials():
    workflow = _workflow("bcal-evaluation.yml")
    upload = _step(workflow, "evaluate-with-bcal", "Upload evaluation results")
    assert upload["if"] == "always()"
    assert "*.bcal/**" in upload["with"]["path"]
    assert "sdk-provider/*.log" in upload["with"]["path"]
    assert ".pfx" not in upload["with"]["path"]
    assert "RUNNER_TEMP" not in upload["with"]["path"]
    cleanup = _step(workflow, "evaluate-with-bcal", "Remove staged evaluation certificate")
    assert cleanup["if"] == "always()"
    assert 'Remove-Item -LiteralPath "$env:RUNNER_TEMP\\llm-api-cert.pfx"' in cleanup["run"]
