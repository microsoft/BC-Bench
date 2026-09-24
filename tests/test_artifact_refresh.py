import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
PWSH = shutil.which("pwsh")
CONFIG = ROOT / "config" / "bc-artifacts.json"
WORKFLOW = ROOT / ".github" / "workflows" / "dataset-validation.yml"


def test_public_artifacts_cover_container_dataset_versions() -> None:
    artifacts = json.loads(CONFIG.read_text(encoding="utf-8"))
    public_versions = {json.loads(line)["environment_setup_version"] for line in (ROOT / "dataset" / "bcbench.jsonl").read_text(encoding="utf-8").splitlines()}
    assert public_versions <= set(artifacts["bcartifacts"])
    assert "bcinsider" not in artifacts
    assert artifacts["bcartifacts"]["27.0"].endswith("/27.0.38460.54596/w1")


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    ("category", "dataset", "version"),
    [
        ("bug-fix", "bcbench.jsonl", "27.0"),
        ("test-generation", "bcbench.jsonl", "27.0"),
        ("data-query", "dataquery.jsonl", "29.0"),
    ],
)
def test_action_uses_public_pin_or_latest_insider_artifact(category: str, dataset: str, version: str, tmp_path: Path) -> None:
    assert PWSH is not None
    entries = (json.loads(line) for line in (ROOT / "dataset" / dataset).read_text(encoding="utf-8").splitlines())
    entry = next(item for item in entries if item["environment_setup_version"] == version)
    action = yaml.safe_load((ROOT / ".github" / "actions" / "setup-bc-container-repo" / "action.yml").read_text(encoding="utf-8"))
    step = next(step for step in action["runs"]["steps"] if step.get("id") == "bcversion")
    assert step["if"] == "inputs.skip-container != 'true'"
    script = step["run"].replace("${{ inputs.instance-id }}", entry["instance_id"]).replace("${{ inputs.category }}", category)
    output = tmp_path / "github-output"
    env = {**os.environ, "GITHUB_OUTPUT": str(output)}
    env.pop("BCBENCH_CANDIDATE_ARTIFACT_URL", None)
    if category == "data-query":
        helper = tmp_path / "BcContainerHelper"
        helper.mkdir()
        (helper / "BcContainerHelper.psm1").write_text(
            """
function Get-BCArtifactUrl {
    param([string]$Version, [string]$Country, [string]$StorageAccount, [string]$Select, [switch]$accept_insiderEula)
    if ($StorageAccount -ne 'bcinsider' -or $Select -ne 'Latest' -or -not $accept_insiderEula) { throw 'Expected latest Insider artifact.' }
    return "https://bcinsider.azureedge.net/sandbox/$Version.99999.0/$Country"
}
Export-ModuleMember -Function Get-BCArtifactUrl
""",
            encoding="utf-8",
        )
        env["PSModulePath"] = str(tmp_path) + os.pathsep + os.environ.get("PSModulePath", "")  # noqa: SIM112 - PowerShell uses this casing on Unix.

    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    outputs = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert outputs["al_tool_dotnet_version"] == ("10.0" if int(version.split(".")[0]) >= 29 else "8.0")
    url = f"https://bcinsider.azureedge.net/sandbox/{version}.99999.0/w1" if category == "data-query" else json.loads(CONFIG.read_text(encoding="utf-8"))["bcartifacts"][version]
    assert outputs["cache_key"] == f"bcartifacts-{hashlib.sha256(url.encode()).hexdigest().upper()}"


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
def test_missing_pinned_artifact_fails_without_latest_fallback() -> None:
    assert PWSH is not None
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", "Import-Module ./scripts/BCBenchUtils.psm1; Get-BCBenchArtifactUrl -Version 99.0"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "No pinned BC artifact URL" in result.stderr


def test_container_setup_uses_same_url_for_container_and_compiler() -> None:
    setup_script = (ROOT / "scripts" / "Setup-ContainerAndRepository.ps1").read_text(encoding="utf-8")
    assert "Get-BCBenchArtifactConfig -Category $Category -Version $Version -Country $Country -CandidateUrl $env:BCBENCH_CANDIDATE_ARTIFACT_URL" in setup_script
    assert "[string] $url = $categoryArtifactConfig.artifactUrl" in setup_script
    assert "New-BCContainerSync" in setup_script
    assert "-ArtifactUrl $url" in setup_script
    assert "New-BCCompilerFolderSync -ContainerName $ContainerName -ArtifactUrl $url" in setup_script


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
def test_latest_candidates_are_resolved_once_per_version(tmp_path: Path) -> None:
    assert PWSH is not None
    helper = tmp_path / "BcContainerHelper"
    helper.mkdir()
    (helper / "BcContainerHelper.psm1").write_text(
        """
function Get-BCArtifactUrl {
    param([string]$version, [string]$country, [string]$select)
    Add-Content -Path $env:RESOLVED_VERSIONS -Value "$version,$country,$select"
    return "https://bcartifacts.azureedge.net/sandbox/$version.99999.0/w1"
}
Export-ModuleMember -Function Get-BCArtifactUrl
""",
        encoding="utf-8",
    )
    entries = (json.loads(line) for line in (ROOT / "dataset" / "bcbench.jsonl").read_text(encoding="utf-8").splitlines())
    selected = [entry for entry in entries if entry["environment_setup_version"] in {"27.0", "27.2"}]
    ids = [entry["instance_id"] for entry in selected if entry["environment_setup_version"] == "27.0"][:2]
    ids.append(next(entry["instance_id"] for entry in selected if entry["environment_setup_version"] == "27.2"))
    output = tmp_path / "github-output"
    calls = tmp_path / "resolved-versions"
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-File", str(ROOT / "scripts" / "Resolve-BCBenchArtifactCandidates.ps1"), "-EntriesJson", json.dumps(ids)],
        env={
            **os.environ,
            "PSModulePath": str(tmp_path) + os.pathsep + os.environ.get("PSModulePath", ""),  # noqa: SIM112 - PowerShell uses this casing on Unix.
            "GITHUB_OUTPUT": str(output),
            "RESOLVED_VERSIONS": str(calls),
        },
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert sorted(calls.read_text(encoding="utf-8").splitlines()) == ["27.0,w1,Latest", "27.2,w1,Latest"]
    candidates = json.loads(output.read_text(encoding="utf-8").removeprefix("artifacts="))
    assert candidates == {
        "27.0": "https://bcartifacts.azureedge.net/sandbox/27.0.99999.0/w1",
        "27.2": "https://bcartifacts.azureedge.net/sandbox/27.2.99999.0/w1",
    }


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
def test_verified_candidates_update_only_public_versions(tmp_path: Path) -> None:
    assert PWSH is not None
    config = tmp_path / "bc-artifacts.json"
    original = json.loads(CONFIG.read_text(encoding="utf-8"))
    config.write_text(json.dumps(original), encoding="utf-8")
    candidates = {
        "27.0": "https://bcartifacts.azureedge.net/sandbox/27.0.99999.0/w1",
        "28.0": "https://bcartifacts.azureedge.net/sandbox/28.0.12345.0/w1",
    }
    result = subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(ROOT / "scripts" / "Update-BCBenchArtifacts.ps1"),
            "-CandidatesJson",
            json.dumps(candidates),
            "-ConfigPath",
            str(config),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    updated = json.loads(config.read_text(encoding="utf-8"))
    assert updated["bcartifacts"] == original["bcartifacts"] | candidates
    assert "bcinsider" not in updated


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
def test_unchanged_candidates_do_not_propose_a_config_change(tmp_path: Path) -> None:
    assert PWSH is not None
    config = tmp_path / "bc-artifacts.json"
    original = CONFIG.read_text(encoding="utf-8")
    config.write_text(original, encoding="utf-8")
    candidates = {"27.0": json.loads(original)["bcartifacts"]["27.0"]}
    result = subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(ROOT / "scripts" / "Update-BCBenchArtifacts.ps1"),
            "-CandidatesJson",
            json.dumps(candidates),
            "-ConfigPath",
            str(config),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert config.read_text(encoding="utf-8").replace("\r\n", "\n") == original.replace("\r\n", "\n")


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
def test_invalid_candidate_never_changes_config(tmp_path: Path) -> None:
    assert PWSH is not None
    config = tmp_path / "bc-artifacts.json"
    original = CONFIG.read_text(encoding="utf-8")
    config.write_text(original, encoding="utf-8")
    candidates = {
        "27.0": "https://bcartifacts.azureedge.net/sandbox/27.0.99999.0/w1",
        "26.0": "https://bcartifacts.azureedge.net/sandbox/27.0.99999.0/w1",
    }
    result = subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(ROOT / "scripts" / "Update-BCBenchArtifacts.ps1"),
            "-CandidatesJson",
            json.dumps(candidates),
            "-ConfigPath",
            str(config),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Invalid BC artifact URL for bcartifacts version 26.0" in result.stderr
    assert config.read_text(encoding="utf-8") == original


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
def test_candidate_override_uses_exact_url_without_changing_pin() -> None:
    assert PWSH is not None
    candidate = "https://bcartifacts.azureedge.net/sandbox/27.0.99999.0/w1"
    result = subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Import-Module ./scripts/BCBenchUtils.psm1; Get-BCBenchArtifactUrl -Version 27.0 -CandidateUrl $env:CANDIDATE",
        ],
        env={**os.environ, "CANDIDATE": candidate},
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == candidate
    assert json.loads(CONFIG.read_text(encoding="utf-8"))["bcartifacts"]["27.0"] != candidate


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    ("candidate", "valid"),
    [
        ("https://bcartifacts.azureedge.net/sandbox/27.0.99999.0/w1", True),
        ("https://bcartifacts.azureedge.net/sandbox/27.2.99999.0/w1", False),
    ],
)
def test_action_cache_tracks_verified_candidate(candidate: str, valid: bool, tmp_path: Path) -> None:
    assert PWSH is not None
    entries = (json.loads(line) for line in (ROOT / "dataset" / "bcbench.jsonl").read_text(encoding="utf-8").splitlines())
    entry = next(item for item in entries if item["environment_setup_version"] == "27.0")
    action = yaml.safe_load((ROOT / ".github" / "actions" / "setup-bc-container-repo" / "action.yml").read_text(encoding="utf-8"))
    script = next(step for step in action["runs"]["steps"] if step.get("id") == "bcversion")["run"]
    for expression, value in {
        "${{ inputs.instance-id }}": entry["instance_id"],
        "${{ inputs.category }}": "bug-fix",
        "${{ inputs.skip-container }}": "false",
    }.items():
        script = script.replace(expression, value)
    output = tmp_path / "github-output"
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", script],
        env={**os.environ, "GITHUB_OUTPUT": str(output), "BCBENCH_CANDIDATE_ARTIFACT_URL": candidate},
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if valid:
        assert result.returncode == 0, result.stderr
        outputs = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
        assert outputs["cache_key"] == f"bcartifacts-{hashlib.sha256(candidate.encode()).hexdigest().upper()}"
    else:
        assert result.returncode != 0
        assert "Invalid BC artifact URL for bcartifacts version 27.0" in result.stderr


def test_only_full_successful_main_verification_proposes_updates() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert jobs["verify-build-and-tests"]["needs"] == ["get-entries", "resolve-artifacts"]
    resolve = jobs["resolve-artifacts"]
    assert resolve["outputs"]["artifacts"] == "${{ steps.resolve.outputs.artifacts }}"
    verify_steps = jobs["verify-build-and-tests"]["steps"]
    select = next(step for step in verify_steps if step.get("name") == "Select latest candidate for this entry")
    setup = next(step for step in verify_steps if step.get("id") == "setup-env")
    assert verify_steps.index(select) < verify_steps.index(setup)
    assert select["env"]["ARTIFACTS_JSON"] == "${{ needs.resolve-artifacts.outputs.artifacts }}"
    assert "BCBENCH_CANDIDATE_ARTIFACT_URL=$url" in select["run"]

    propose = jobs["propose-artifacts"]
    assert propose["needs"] == ["get-entries", "resolve-artifacts", "verify-build-and-tests"]
    condition = propose["if"]
    assert "needs.verify-build-and-tests.result == 'success'" in condition
    assert "!inputs.test-run && !inputs.modified-only" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert propose["permissions"] == {"contents": "write", "pull-requests": "write"}
    run = propose["steps"][-1]["run"]
    assert "git diff --quiet -- config/bc-artifacts.json" in run
    assert "gh pr create --base main" in run
    assert "gh pr merge $branch --auto --squash" in run
