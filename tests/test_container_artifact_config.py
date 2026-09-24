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


def test_pinned_artifacts_cover_container_dataset_versions() -> None:
    artifacts = json.loads(CONFIG.read_text(encoding="utf-8"))
    public_versions = {json.loads(line)["environment_setup_version"] for line in (ROOT / "dataset" / "bcbench.jsonl").read_text(encoding="utf-8").splitlines()}
    insider_versions = {json.loads(line)["environment_setup_version"] for line in (ROOT / "dataset" / "dataquery.jsonl").read_text(encoding="utf-8").splitlines()}
    assert public_versions <= set(artifacts["bcartifacts"])
    assert insider_versions <= set(artifacts["bcinsider"])
    assert artifacts["bcartifacts"]["27.0"].endswith("/27.0.38460.54596/w1")


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
def test_action_uses_exact_pinned_artifact_or_skips_container(category: str, dataset: str, version: str | None, skip_container: bool, tmp_path: Path) -> None:
    assert PWSH is not None
    entries = (json.loads(line) for line in (ROOT / "dataset" / dataset).read_text(encoding="utf-8").splitlines())
    entry = next(item for item in entries if version is None or item["environment_setup_version"] == version)
    action = yaml.safe_load((ROOT / ".github" / "actions" / "setup-bc-container-repo" / "action.yml").read_text(encoding="utf-8"))
    script = next(step for step in action["runs"]["steps"] if step.get("id") == "bcversion")["run"]
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
        account = "bcinsider" if category == "data-query" else "bcartifacts"
        url = json.loads(CONFIG.read_text(encoding="utf-8"))[account][version]
        assert outputs["cache_key"] == f"bcartifacts-{hashlib.sha256(url.encode()).hexdigest().upper()}"


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required")
def test_missing_pinned_artifact_fails_without_latest_fallback() -> None:
    assert PWSH is not None
    result = subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-Command", "Import-Module ./scripts/BCBenchUtils.psm1; Get-BCBenchPinnedArtifactUrl -Version 99.0 -Category bug-fix"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "No pinned BC artifact URL" in result.stderr


def test_verifier_uses_same_pins_without_refreshing_them() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "dataset-validation.yml").read_text(encoding="utf-8"))
    assert set(workflow["jobs"]) == {"get-entries", "verify-build-and-tests"}
    setup = next(step for step in workflow["jobs"]["verify-build-and-tests"]["steps"] if step.get("id") == "setup-env")
    assert "artifact-urls" not in setup["with"]
    setup_script = (ROOT / "scripts" / "Setup-ContainerAndRepository.ps1").read_text(encoding="utf-8")
    assert "Get-BCBenchPinnedArtifactUrl -Version $Version -Category $Category" in setup_script
    assert "New-BCContainerSync" in setup_script
    assert "-ArtifactUrl $url" in setup_script
    assert "New-BCCompilerFolderSync -ContainerName $ContainerName -ArtifactUrl $url" in setup_script
