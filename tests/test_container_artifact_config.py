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
INSIDER_URL = "https://bcinsider-fvh2ekdjecfjd6gk.b02.azurefd.net/sandbox/29.0.99999.88888/w1"
MOCK_INSIDER_LOOKUP = f"""
function global:Get-BCArtifactUrl {{
    param($Version, $Country, $StorageAccount, $Select, [switch]$accept_insiderEula)
    if ($Version -ne '29.0' -or $Country -ne 'w1' -or $StorageAccount -ne 'bcinsider' -or $Select -ne 'Latest' -or -not $accept_insiderEula) {{
        throw 'Unexpected BC Insider artifact lookup'
    }}
    return '{INSIDER_URL}'
}}
"""


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
def test_pinned_artifacts_cover_container_dataset_versions() -> None:
    assert PWSH is not None
    public_versions = {json.loads(line)["environment_setup_version"] for line in (ROOT / "dataset" / "bcbench.jsonl").read_text(encoding="utf-8").splitlines()}
    versions = sorted(public_versions)
    script = "Import-Module ./scripts/BCBenchUtils.psm1 -DisableNameChecking; " + "; ".join(f"(Get-BCBenchArtifactConfig -Category bug-fix -Version '{version}').artifactUrl" for version in versions)
    result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", script], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    urls = dict(zip(versions, result.stdout.splitlines(), strict=True))
    assert all(url.startswith("https://bcartifacts-") and url.endswith("/w1") and f"/sandbox/{version}." in url for version, url in urls.items())
    assert urls["27.0"] == "https://bcartifacts-exdbf9fwegejdqak.b02.azurefd.net/sandbox/27.0.38460.54596/w1"


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
@pytest.mark.parametrize(
    ("category", "dataset", "version", "skip_container"),
    [
        ("bug-fix", "bcbench.jsonl", "27.0", False),
        ("test-generation", "bcbench.jsonl", "27.0", False),
        ("data-query", "dataquery.jsonl", "29.0", False),
        ("code-review", "codereview.jsonl", None, True),
    ],
)
def test_action_uses_configured_artifact_or_skips_container(category: str, dataset: str, version: str | None, skip_container: bool, tmp_path: Path) -> None:
    assert PWSH is not None
    entries = (json.loads(line) for line in (ROOT / "dataset" / dataset).read_text(encoding="utf-8").splitlines())
    entry = next((item for item in entries if version is None or item["environment_setup_version"] == version), None)
    assert entry is not None, f"No entry in {dataset} for version {version}"
    action = yaml.safe_load((ROOT / ".github" / "actions" / "setup-bc-container-repo" / "action.yml").read_text(encoding="utf-8"))
    script = next(step for step in action["runs"]["steps"] if step.get("id") == "bcversion")["run"]
    if category == "data-query":
        script = script.replace(
            "Import-Module ./scripts/BCBenchUtils.psm1 -Force -DisableNameChecking", "Import-Module ./scripts/BCBenchUtils.psm1 -Force -DisableNameChecking\n" + MOCK_INSIDER_LOOKUP
        )
    for expression, value in {
        "${{ inputs.instance-id }}": entry["instance_id"],
        "${{ inputs.category }}": category,
        "${{ inputs.skip-container }}": str(skip_container).lower(),
    }.items():
        script = script.replace(expression, value)

    output = tmp_path / "github-output"
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", script],
        cwd=ROOT,
        env={**os.environ, "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    outputs = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert outputs["al_tool_dotnet_version"] == ("10.0" if int(entry["environment_setup_version"].split(".")[0]) >= 29 else "8.0")
    if skip_container:
        assert "cache_key" not in outputs
    else:
        url = INSIDER_URL if category == "data-query" else "https://bcartifacts-exdbf9fwegejdqak.b02.azurefd.net/sandbox/27.0.38460.54596/w1"
        assert outputs["cache_key"] == f"bcartifacts-{hashlib.sha256(url.encode()).hexdigest().upper()}"


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
def test_missing_pinned_artifact_fails_without_latest_fallback() -> None:
    assert PWSH is not None
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", "Import-Module ./scripts/BCBenchUtils.psm1; Get-BCBenchArtifactConfig -Version 99.0 -Category bug-fix"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "No pinned BC artifact URL" in result.stderr


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
def test_missing_insider_artifact_fails() -> None:
    assert PWSH is not None
    result = subprocess.run(
        [
            PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Import-Module ./scripts/BCBenchUtils.psm1; function global:Get-BCArtifactUrl { return $null }; Get-BCBenchArtifactConfig -Version 29.0 -Category data-query",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "No BC Insider artifact URL resolved" in result.stderr


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
def test_public_artifacts_reject_unconfigured_country() -> None:
    assert PWSH is not None
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", "Import-Module ./scripts/BCBenchUtils.psm1; Get-BCBenchArtifactConfig -Version 27.0 -Category bug-fix -Country us"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "only configured for w1" in result.stderr


def test_verifier_uses_same_pins_without_refreshing_them() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "dataset-validation.yml").read_text(encoding="utf-8"))
    assert set(workflow["jobs"]) == {"get-entries", "verify-build-and-tests"}
    setup = next(step for step in workflow["jobs"]["verify-build-and-tests"]["steps"] if step.get("id") == "setup-env")
    assert "artifact-urls" not in setup["with"]
    setup_script = (ROOT / "scripts" / "Setup-ContainerAndRepository.ps1").read_text(encoding="utf-8")
    assert "Get-BCBenchArtifactConfig -Category $Category -Version $Version -Country $Country" in setup_script
    assert "New-BCContainerSync" in setup_script
    assert "-ArtifactUrl $url" in setup_script
    assert "New-BCCompilerFolderSync -ContainerName $ContainerName -ArtifactUrl $url" in setup_script
