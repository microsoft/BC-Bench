import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"
SELECTED_DATASET = "${{ inputs.dataset || 'gold' }}"
OPTIONAL_DATASET_ARGUMENT = 'if [[ -n "$NL2AL_DATASET" ]]; then\n  cmd+=(--dataset "$NL2AL_DATASET")\nfi'
INSTALL_SCRIPT = WORKFLOWS.parents[1] / "scripts" / "Install-BCalTool.ps1"
INSTALL_ACTION = WORKFLOWS.parent / "actions" / "install-bcal" / "action.yml"
PWSH = shutil.which("pwsh")
PACKAGE_ID = "Example.BCal"
FEED_URL = "https://example.invalid/nuget/index.json"


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _step(workflow: dict, job: str, name: str) -> dict:
    return next(step for step in workflow["jobs"][job]["steps"] if step.get("name") == name)


def test_bcal_dataset_choices_default_to_gold_for_dispatch_and_schedule() -> None:
    workflow = _workflow("bcal-evaluation.yml")
    dispatch = workflow[True]["workflow_dispatch"]["inputs"]
    dataset = dispatch["dataset"]

    assert dataset == {
        "description": "NL2AL dataset to evaluate",
        "required": False,
        "default": "gold",
        "type": "choice",
        "options": ["gold", "challenge", "multiturn"],
    }
    assert workflow[True]["schedule"]
    assert workflow["env"]["NL2AL_DATASET"] == SELECTED_DATASET
    assert workflow["jobs"]["get-entries"]["with"]["dataset"] == SELECTED_DATASET
    assert workflow["jobs"]["summarize-results"]["with"]["dataset"] == SELECTED_DATASET


def test_bcal_run_name_and_concurrency_identify_the_selected_dataset() -> None:
    workflow = _workflow("bcal-evaluation.yml")

    assert SELECTED_DATASET in workflow["run-name"]
    assert workflow["concurrency"]["group"] == f"bcal-evaluation-{SELECTED_DATASET}-${{{{ inputs.test-run && 'test' || 'full' }}}}"
    assert workflow["concurrency"]["cancel-in-progress"] is False


@pytest.mark.parametrize("workflow_name", ["get-entries.yml", "summarize-results.yml"])
def test_reusable_workflow_dataset_input_is_optional_without_a_gold_default(workflow_name: str) -> None:
    workflow = _workflow(workflow_name)
    dataset = workflow[True]["workflow_call"]["inputs"]["dataset"]

    assert dataset["type"] == "string"
    assert dataset["required"] is False
    assert dataset["default"] == ""
    assert workflow["jobs"][workflow_name.removesuffix(".yml")]["env"]["NL2AL_DATASET"] == "${{ inputs.dataset }}"


@pytest.mark.parametrize(
    ("workflow_name", "job", "step_name", "command"),
    [
        ("get-entries.yml", "get-entries", "Get entries for matrix", "dataset list"),
        ("summarize-results.yml", "summarize-results", "Summarize evaluation results", "result summarize"),
    ],
)
def test_optional_dataset_is_passed_as_a_quoted_array_argument(workflow_name: str, job: str, step_name: str, command: str) -> None:
    workflow = _workflow(workflow_name)
    step = _step(workflow, job, step_name)
    script = step["run"]

    assert step["shell"] == "bash"
    assert f"cmd=(uv run bcbench {command}" in script
    assert '--category "$EVALUATION_CATEGORY"' in script
    assert OPTIONAL_DATASET_ARGUMENT in script
    assert script.strip().endswith('"${cmd[@]}"')
    assert "${{ inputs." not in script
    assert 'eval "$cmd"' not in script
    assert workflow["jobs"][job]["env"]["EVALUATION_CATEGORY"] == "${{ inputs.category }}"


def test_get_entries_keeps_modified_only_precedence_over_test_run() -> None:
    workflow = _workflow("get-entries.yml")
    step = _step(workflow, "get-entries", "Get entries for matrix")

    assert step["env"] == {"MODIFIED_ONLY": "${{ inputs.modified-only }}", "TEST_RUN": "${{ inputs.test-run }}"}
    assert 'if [[ "$MODIFIED_ONLY" == "true" ]]; then\n  cmd+=(--modified-only)' in step["run"]
    assert 'elif [[ "$TEST_RUN" == "true" ]]; then\n  cmd+=(--test-run)' in step["run"]
    assert "--github-output entries" in step["run"]


def test_bcal_resolves_bc_version_from_the_selected_dataset() -> None:
    workflow = _workflow("bcal-evaluation.yml")
    job = workflow["jobs"]["evaluate-with-bcal"]
    step = _step(workflow, "evaluate-with-bcal", "Resolve BC version for cache key")
    cache = _step(workflow, "evaluate-with-bcal", "Cache BC sandbox artifacts")

    assert job["env"]["INSTANCE_ID"] == "${{ matrix.entry }}"
    assert step["id"] == "bcversion"
    assert step["shell"] == "pwsh"
    assert 'bcbench dataset version "$env:INSTANCE_ID"' in step["run"]
    assert '--dataset "$env:NL2AL_DATASET"' in step["run"]
    assert "--category nl2al --dataset" in step["run"]
    assert "--github-output version" in step["run"]
    assert cache["with"]["key"] == "bcartifacts-${{ steps.bcversion.outputs.version }}"


def test_symbol_download_uses_the_exact_dataset_path_output_without_fallback() -> None:
    workflow = _workflow("bcal-evaluation.yml")
    step = _step(workflow, "evaluate-with-bcal", "Download BC Application symbols")

    assert step["env"]["DATASET_PATH"] == "${{ steps.bcversion.outputs.dataset-path }}"
    assert "[string]::IsNullOrWhiteSpace($env:DATASET_PATH)" in step["run"]
    assert 'throw "bcbench dataset version did not return a dataset-path."' in step["run"]
    assert '-InstanceId "$env:INSTANCE_ID" -DatasetPath "$env:DATASET_PATH"' in step["run"]
    assert step["run"].index("throw ") < step["run"].index("Download-BCSymbols.ps1")
    for name in ("bcal-evaluation.yml", "get-entries.yml", "summarize-results.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "nl2al.jsonl" not in text
        assert "nl2al_challenge.jsonl" not in text
        assert "nl2al_multiturn.jsonl" not in text


def test_bcal_evaluation_receives_the_dataset_and_keeps_the_native_llm_bridge() -> None:
    workflow = _workflow("bcal-evaluation.yml")
    step = _step(workflow, "evaluate-with-bcal", "Run BCal for entry ${{ matrix.entry }}")
    bridge = _step(workflow, "evaluate-with-bcal", "Build bc-eval LLM API bridge venv")

    assert 'bcbench evaluate bcal "$env:INSTANCE_ID" --dataset "$env:NL2AL_DATASET"' in step["run"]
    assert '--output-dir "$env:EVALUATION_RESULTS_DIR"' in step["run"]
    assert "bc_eval_llm_api_bridge.py" in step["run"]
    assert "$env:BCAL_LLM_COMMAND" in step["run"]
    assert '"bc-eval==0.6.1"' in bridge["run"]


def test_scenario_metadata_is_uploaded_separately_from_result_jsonl() -> None:
    workflow = _workflow("bcal-evaluation.yml")
    results = _step(workflow, "evaluate-with-bcal", "Upload evaluation results")
    scenario = _step(workflow, "evaluate-with-bcal", "Upload BCal scenario execution metadata")

    assert results["with"]["name"].startswith("evaluation-results-")
    assert scenario["with"]["name"].startswith("bcal-scenario-")
    assert results["with"]["path"].splitlines() == [
        "${{ env.EVALUATION_RESULTS_DIR }}/**/*.jsonl",
        "!${{ env.EVALUATION_RESULTS_DIR }}/**/bcal-scenario/**",
    ]
    assert scenario["with"]["path"] == "${{ env.EVALUATION_RESULTS_DIR }}/**/bcal-scenario/**"
    assert results["with"]["if-no-files-found"] == "error"
    assert scenario["with"]["if-no-files-found"] == "ignore"
    assert "always()" in results["if"]
    assert "always()" in scenario["if"]
    assert results["with"]["retention-days"] == scenario["with"]["retention-days"] == "${{ inputs.test-run && 1 || 30 }}"


def test_summary_runs_after_matrix_failures_but_not_cancellation_or_an_empty_matrix() -> None:
    workflow = _workflow("bcal-evaluation.yml")
    summary = workflow["jobs"]["summarize-results"]

    assert set(summary["needs"]) == {"get-entries", "evaluate-with-bcal"}
    assert summary["if"] == "${{ always() && !cancelled() && needs.get-entries.result == 'success' && needs.get-entries.outputs.entries != '[]' }}"
    assert workflow["jobs"]["evaluate-with-bcal"]["strategy"]["fail-fast"] is False
    assert summary["with"]["results-dir"] == "${{ needs.evaluate-with-bcal.outputs.results-dir || 'evaluation_results' }}"


def test_selected_dataset_downloads_only_result_artifacts_while_legacy_ci_still_works() -> None:
    workflow = _workflow("summarize-results.yml")
    download = _step(workflow, "summarize-results", "Download all evaluation results")
    ci = _workflow("CI.yml")
    mock_upload = _step(ci, "mock-evaluation", "Upload mock evaluation results")

    assert download["with"]["pattern"] == "${{ inputs.dataset != '' && 'evaluation-results-*' || '*' }}"
    assert download["with"]["merge-multiple"] is True
    assert "dataset" not in ci["jobs"]["summarize-results"]["with"]
    assert not mock_upload["with"]["name"].startswith("evaluation-results-")


def test_summary_passes_selected_dataset_and_preserves_failure_signals() -> None:
    workflow = _workflow("summarize-results.yml")
    summary = _step(workflow, "summarize-results", "Summarize evaluation results")
    upload = _step(workflow, "summarize-results", "Upload evaluation summary to artifacts")

    assert OPTIONAL_DATASET_ARGUMENT in summary["run"]
    assert '--result-dir "$RESULTS_DIR"' in summary["run"]
    assert '--git-ref "$EVALUATION_GIT_REF"' in summary["run"]
    assert "|| true" not in summary["run"]
    assert not summary.get("continue-on-error", False)
    assert upload["with"]["if-no-files-found"] == "error"


def test_bceval_run_tags_append_dataset_without_replacing_existing_run_identity() -> None:
    workflow = _workflow("summarize-results.yml")
    upload = _step(workflow, "summarize-results", "Upload result using bceval")
    script = upload["run"]

    assert 'RUN_TAGS="${EVALUATION_AGENT},${MODEL_TAG},${BRANCH_TAG}"' in script
    assert 'RUN_NAME="${EVALUATION_AGENT} (${EVALUATION_MODEL}) - #${GITHUB_RUN_ID}"' in script
    assert ('if [[ -n "$NL2AL_DATASET" ]]; then\n  RUN_NAME="${RUN_NAME} [${NL2AL_DATASET}]"\n  RUN_TAGS="${RUN_TAGS},dataset-${NL2AL_DATASET}"\nfi') in script
    assert '--tags "$RUN_TAGS"' in script
    assert '--eval-run-name "$RUN_NAME"' in script
    assert "EvalRunType" not in script
    assert "--experiment" not in script
    assert "bc-eval==0.6.1" in script
    assert "${{ inputs.dataset }}" not in script


def test_bcal_test_runs_do_not_upload_to_kusto_or_update_the_leaderboard() -> None:
    bcal = _workflow("bcal-evaluation.yml")
    workflow = _workflow("summarize-results.yml")
    summary_inputs = bcal["jobs"]["summarize-results"]["with"]
    upload = _step(workflow, "summarize-results", "Upload result using bceval")
    leaderboard = _step(workflow, "summarize-results", "Update leaderboard in a new branch")

    assert summary_inputs["mock"] == "${{ inputs.test-run || false }}"
    assert summary_inputs["skip-leaderboard"] is True
    assert "${{ !inputs.mock && '--storage braintrust --storage kusto' || '' }}" in upload["run"]
    assert upload["run"].count("--storage kusto") == 1
    assert leaderboard["if"] == "${{ !inputs.mock && !inputs.skip-leaderboard }}"


@pytest.mark.parametrize("workflow_name", ["get-entries.yml", "summarize-results.yml"])
def test_existing_callers_can_omit_the_dataset_input(workflow_name: str) -> None:
    inputs = _workflow(workflow_name)[True]["workflow_call"]["inputs"]
    callers_without_dataset = []
    for path in WORKFLOWS.glob("*.yml"):
        for job in _workflow(path.name).get("jobs", {}).values():
            if job.get("uses", "").endswith(f"/{workflow_name}") and "dataset" not in job.get("with", {}):
                callers_without_dataset.append(path.name)
                assert set(job["with"]).issubset(inputs)
                assert all(not config.get("required", False) or key in job["with"] for key, config in inputs.items())

    assert callers_without_dataset


def test_bcal_version_selection_defaults_to_latest_prerelease_for_dispatch_and_schedule() -> None:
    workflow = _workflow("bcal-evaluation.yml")
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    mode = inputs["bcal-version-mode"]
    version = inputs["bcal-version"]

    assert mode["type"] == "choice"
    assert mode["default"] == "latest-prerelease"
    assert mode["options"] == ["latest-prerelease", "pinned"]
    assert mode["required"] is False
    assert version["type"] == "string"
    assert version["default"] == ""
    assert version["required"] is False
    assert workflow["env"]["BCAL_VERSION_MODE"] == "${{ inputs.bcal-version-mode || 'latest-prerelease' }}"
    assert workflow["env"]["BCAL_REQUESTED_VERSION"] == "${{ inputs.bcal-version }}"


def test_bcal_installed_version_output_flows_to_evaluation_metadata() -> None:
    workflow = _workflow("bcal-evaluation.yml")
    install = _step(workflow, "evaluate-with-bcal", "Install bcal CLI from internal feed")
    evaluate = _step(workflow, "evaluate-with-bcal", "Run BCal for entry ${{ matrix.entry }}")
    action = yaml.safe_load(INSTALL_ACTION.read_text(encoding="utf-8"))
    action_install = next(step for step in action["runs"]["steps"] if step.get("id") == "install")

    assert install["id"] == "install-bcal"
    assert install["uses"] == "$/.github/actions/install-bcal"
    assert action["outputs"]["version"]["value"] == "${{ steps.install.outputs.version }}"
    assert ".\\scripts\\Install-BCalTool.ps1" in action_install["run"]
    assert '-VersionMode "$env:BCAL_VERSION_MODE"' in action_install["run"]
    assert '-Version "$env:BCAL_REQUESTED_VERSION"' in action_install["run"]
    assert '-PackageId "$env:BCAL_PACKAGE_ID"' in action_install["run"]
    assert '-FeedUrl "$env:BCAL_FEED_URL"' in action_install["run"]
    assert "${{ inputs." not in action_install["run"]
    assert evaluate["env"]["BCAL_PACKAGE_VERSION"] == "${{ steps.install-bcal.outputs.version }}"
    assert "[string]::IsNullOrWhiteSpace($env:BCAL_PACKAGE_VERSION)" in evaluate["run"]
    assert evaluate["run"].index("BCAL_PACKAGE_VERSION") < evaluate["run"].index("bcbench evaluate bcal")


def test_bcal_matrix_uses_requested_mode_without_a_run_wide_resolver() -> None:
    workflow = _workflow("bcal-evaluation.yml")
    matrix = workflow["jobs"]["evaluate-with-bcal"]
    install = _step(workflow, "evaluate-with-bcal", "Install bcal CLI from internal feed")

    assert "resolve-bcal-version" not in workflow["jobs"]
    assert matrix["needs"] == "get-entries"
    assert install["with"]["version-mode"] == "${{ env.BCAL_VERSION_MODE }}"
    assert install["with"]["version"] == "${{ env.BCAL_REQUESTED_VERSION }}"
    assert len([step for step in matrix["steps"] if step.get("uses") == "$/.github/actions/install-bcal"]) == 1


def test_bcal_matrix_keeps_the_existing_installation_and_authentication() -> None:
    workflow = _workflow("bcal-evaluation.yml")
    matrix = _step(workflow, "evaluate-with-bcal", "Install bcal CLI from internal feed")
    action = yaml.safe_load(INSTALL_ACTION.read_text(encoding="utf-8"))
    login = action["runs"]["steps"][0]
    action_install = next(step for step in action["runs"]["steps"] if step.get("id") == "install")

    assert matrix["uses"] == "$/.github/actions/install-bcal"
    assert matrix["with"]["client-id"] == "${{ secrets.AZURE_CLIENT_ID }}"
    assert matrix["with"]["tenant-id"] == "${{ secrets.AZURE_TENANT_ID }}"
    assert matrix["with"]["package-id"] == "${{ secrets.BCAL_PACKAGE_ID }}"
    assert matrix["with"]["feed-url"] == "${{ secrets.BCAL_FEED_URL }}"
    assert workflow["jobs"]["evaluate-with-bcal"]["environment"] == {"name": "ado-read", "deployment": False}
    assert workflow["jobs"]["evaluate-with-bcal"]["permissions"] == {"contents": "read", "id-token": "write"}
    assert action["runs"]["using"] == "composite"
    assert action["inputs"]["version-mode"]["required"] is True
    assert login["uses"] == "azure/login@a641126d1b8aa4d1fa005f4f92df94a3a4c4c906"
    assert login["with"] == {
        "client-id": "${{ inputs.client-id }}",
        "tenant-id": "${{ inputs.tenant-id }}",
        "allow-no-subscriptions": True,
    }
    assert action_install["env"]["BCAL_VERSION_MODE"] == "${{ inputs.version-mode }}"
    assert action_install["env"]["BCAL_REQUESTED_VERSION"] == "${{ inputs.version }}"
    assert "dotnet tool install --global Microsoft.Artifacts.CredentialProvider.NuGet.Tool" in action["runs"]["steps"][1]["run"]
    assert "az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798" in action_install["run"]


def test_bcal_package_selection_does_not_change_model_or_judge_selection() -> None:
    workflow = _workflow("bcal-evaluation.yml")
    model = workflow[True]["workflow_dispatch"]["inputs"]["external-model"]
    summary = _workflow("summarize-results.yml")
    upload = _step(summary, "summarize-results", "Upload result using bceval")

    assert model["default"] == "gpt-55-chat"
    assert model["options"] == ["gpt-56-reasoning-nano-luna", "gpt-56-reasoning-sol", "gpt-55-chat"]
    assert workflow["jobs"]["summarize-results"]["with"]["model"] == "${{ inputs.external-model || 'gpt-55-chat' }}"
    assert upload["env"]["JUDGE_MODEL"] == "${{ steps.bceval.outputs.judge_model }}"


def _install_bcal_tool(
    *,
    mode: str = "latest-prerelease",
    version: str = "",
    installed_packages: list[dict] | None = None,
    list_output: str | None = None,
    install_exit_codes: list[int] | None = None,
    list_exit_code: int = 0,
) -> dict:
    assert PWSH is not None
    packages = installed_packages if installed_packages is not None else [{"packageId": PACKAGE_ID, "version": "1.2.3-preview.4", "commands": ["bcal"]}]
    case = {
        "package_id": PACKAGE_ID,
        "feed_url": FEED_URL,
        "mode": mode,
        "version": version,
        "list_output": list_output if list_output is not None else json.dumps({"version": 1, "data": packages}),
        "install_exit_codes": install_exit_codes or [0],
        "list_exit_code": list_exit_code,
    }
    result = subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            r"""
            $ErrorActionPreference = "Stop"
            $case = $env:BCAL_INSTALL_TEST_CASE | ConvertFrom-Json -AsHashtable
            $global:BcalTestCalls = [System.Collections.Generic.List[object]]::new()
            $global:BcalTestOutputs = [System.Collections.Generic.List[string]]::new()
            $global:BcalTestSleeps = [System.Collections.Generic.List[int]]::new()
            $global:BcalTestInstallCount = 0
            function dotnet {
                $global:BcalTestCalls.Add(@($args))
                if ($args[0] -eq "tool" -and $args[1] -eq "install") {
                    if ($global:BcalTestInstallCount -ge $case.install_exit_codes.Count) {
                        throw "Unexpected extra installation attempt."
                    }
                    $global:LASTEXITCODE = $case.install_exit_codes[$global:BcalTestInstallCount]
                    $global:BcalTestInstallCount++
                    return
                }
                if ($args[0] -eq "tool" -and $args[1] -eq "list") {
                    $global:LASTEXITCODE = $case.list_exit_code
                    $case.list_output
                    return
                }
                throw "Unexpected dotnet command."
            }
            function Add-Content {
                param([string]$LiteralPath, [string]$Value, [string]$Encoding)
                if ($LiteralPath -ne "bcal-install-test-output") { throw "Unexpected output path." }
                $global:BcalTestOutputs.Add($Value)
            }
            function Start-Sleep {
                param([int]$Seconds)
                $global:BcalTestSleeps.Add($Seconds)
            }
            $env:GITHUB_OUTPUT = "bcal-install-test-output"
            $failure = ""
            try {
                & $env:BCAL_INSTALL_TEST_SCRIPT `
                    -PackageId $case.package_id -FeedUrl $case.feed_url `
                    -VersionMode $case.mode -Version $case.version | Out-Null
            }
            catch {
                $failure = $_.Exception.Message
            }
            @{
                calls = $global:BcalTestCalls.ToArray()
                outputs = $global:BcalTestOutputs.ToArray()
                sleeps = $global:BcalTestSleeps.ToArray()
                error = $failure
            } | ConvertTo-Json -Compress -Depth 6
            """,
        ],
        env={
            **os.environ,
            "PATH": "",
            "BCAL_INSTALL_TEST_CASE": json.dumps(case),
            "BCAL_INSTALL_TEST_SCRIPT": str(INSTALL_SCRIPT),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
@pytest.mark.parametrize(
    ("mode", "version", "actual_version"),
    [
        ("latest-prerelease", "", "7.8.9-preview.10"),
        ("latest-prerelease", " \t", "7.8.9-preview.10"),
        ("latest-prerelease", "", "18.0.38.47039-beta"),
        ("pinned", "7.8.9", "7.8.9"),
        ("pinned", "7.8.9-preview.10", "7.8.9-preview.10"),
        ("pinned", "7.8.9.1", "7.8.9.1"),
        ("pinned", "7.8.9+build.10", "7.8.9+build.10"),
        ("pinned", "18.0.38.47039-beta", "18.0.38.47039-beta"),
    ],
)
def test_bcal_install_uses_the_selected_mode_and_records_the_actual_version(mode: str, version: str, actual_version: str) -> None:
    result = _install_bcal_tool(
        mode=mode,
        version=version,
        installed_packages=[{"packageId": PACKAGE_ID, "version": actual_version, "commands": ["bcal"]}],
    )
    version_arguments = ["--version", version] if mode == "pinned" else ["--prerelease"]

    assert result["error"] == ""
    assert result["calls"] == [
        ["tool", "install", "--global", PACKAGE_ID, *version_arguments, "--add-source", FEED_URL],
        ["tool", "list", PACKAGE_ID, "--global", "--format", "json"],
    ]
    assert result["outputs"] == [f"version={actual_version}"]
    assert result["sleeps"] == []


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
@pytest.mark.parametrize(
    ("mode", "version"),
    [
        ("latest-prerelease", "1.2.3"),
        ("latest-prerelease", "1.*"),
        ("pinned", ""),
        ("pinned", " \t"),
        ("pinned", "*"),
        ("pinned", "1.2.*"),
        ("pinned", "[1.2.3]"),
        ("pinned", "[1.2.3,2.0.0)"),
        ("pinned", "latest"),
        ("pinned", "1.2.3\n"),
        ("pinned", "1.2.3 --prerelease"),
        ("pinned", "$(Write-Output injected)"),
        ("pinned", "1.2.3; Write-Output injected"),
        ("unknown-mode", ""),
    ],
)
def test_bcal_invalid_version_selection_fails_before_dotnet(mode: str, version: str) -> None:
    result = _install_bcal_tool(mode=mode, version=version)

    assert result["error"]
    assert result["calls"] == []
    assert result["outputs"] == []
    assert result["sleeps"] == []


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
def test_bcal_installed_version_lookup_is_case_insensitive_and_package_scoped() -> None:
    result = _install_bcal_tool(
        installed_packages=[
            {"packageId": "Credential.Provider", "version": "99.0.0", "commands": ["credential-provider"]},
            {"packageId": f"{PACKAGE_ID}.Extra", "version": "98.0.0", "commands": ["other"]},
            {"packageId": PACKAGE_ID.upper(), "version": "2.3.4-preview.5", "commands": ["bcal", "bcal-shell"]},
        ]
    )

    assert result["error"] == ""
    assert result["outputs"] == ["version=2.3.4-preview.5"]


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
@pytest.mark.parametrize(
    ("packages", "error"),
    [
        ([], "found 0"),
        ([{"packageId": f"{PACKAGE_ID}.Extra", "version": "1.2.3"}], "found 0"),
        (
            [{"packageId": PACKAGE_ID, "version": "1.2.3"}, {"packageId": PACKAGE_ID.lower(), "version": "1.2.3"}],
            "found 2",
        ),
        ([{"packageId": PACKAGE_ID, "version": "unknown"}], "Invalid installed-version data"),
        ([{"packageId": PACKAGE_ID, "version": ""}], "Invalid installed-version data"),
        ([{"packageId": PACKAGE_ID, "version": None}], "Invalid installed-version data"),
        ([{"packageId": PACKAGE_ID, "version": 1}], "Invalid installed-version data"),
        ([{"packageId": PACKAGE_ID}], "Invalid installed-version data"),
    ],
)
def test_bcal_missing_ambiguous_or_malformed_installed_version_fails_without_metadata(packages: list[dict], error: str) -> None:
    result = _install_bcal_tool(installed_packages=packages)

    assert error in result["error"]
    assert result["outputs"] == []


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
@pytest.mark.parametrize(
    "list_output",
    [
        "",
        "not JSON",
        "null",
        "[]",
        "{}",
        '{"version":1}',
        '{"version":1,"data":null}',
        '{"version":1,"data":{}}',
        '{"version":2,"data":[]}',
    ],
)
def test_bcal_invalid_tool_list_json_fails_without_metadata(list_output: str) -> None:
    result = _install_bcal_tool(list_output=list_output)

    assert "dotnet tool list returned" in result["error"]
    assert result["outputs"] == []


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
def test_bcal_installed_version_must_match_the_requested_pin() -> None:
    result = _install_bcal_tool(mode="pinned", version="1.2.3", installed_packages=[{"packageId": PACKAGE_ID, "version": "1.2.4", "commands": ["bcal"]}])

    assert "does not match requested version '1.2.3'" in result["error"]
    assert result["outputs"] == []


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
def test_bcal_tool_list_failure_is_not_recorded_as_success() -> None:
    result = _install_bcal_tool(list_exit_code=1)

    assert "dotnet tool list failed" in result["error"]
    assert result["outputs"] == []


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
def test_bcal_transient_install_failure_retries_the_same_exact_pin() -> None:
    result = _install_bcal_tool(mode="pinned", version="1.2.3-preview.4", install_exit_codes=[1, 1, 0])

    assert result["error"] == ""
    assert result["calls"][:3] == [["tool", "install", "--global", PACKAGE_ID, "--version", "1.2.3-preview.4", "--add-source", FEED_URL]] * 3
    assert result["calls"][3] == ["tool", "list", PACKAGE_ID, "--global", "--format", "json"]
    assert result["outputs"] == ["version=1.2.3-preview.4"]
    assert result["sleeps"] == [20, 20]


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required to test BCal package installation")
def test_bcal_install_failure_never_publishes_version_metadata() -> None:
    result = _install_bcal_tool(install_exit_codes=[1, 1, 1])

    assert "install failed after 3 attempts" in result["error"]
    assert len(result["calls"]) == 3
    assert all(call[:2] == ["tool", "install"] for call in result["calls"])
    assert result["outputs"] == []
    assert result["sleeps"] == [20, 20]
