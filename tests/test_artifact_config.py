import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
UTILS_MODULE = ROOT / "scripts" / "BCBenchUtils.psm1"


def get_artifact_config(category: str, version: str) -> dict[str, object]:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell is required")

    command = f"Import-Module '{UTILS_MODULE}' -Force -DisableNameChecking; Get-BCBenchArtifactConfig -Category '{category}' -Version '{version}' | ConvertTo-Json -Compress"
    result = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def test_released_bug_fix_uses_public_artifacts():
    assert get_artifact_config("bug-fix", "28.0") == {}


@pytest.mark.parametrize("category", ["bug-fix", "test-generation"])
@pytest.mark.parametrize("version", ["29.0", "30.0"])
def test_insider_bug_fix_versions_use_insider_artifacts(category: str, version: str):
    assert get_artifact_config(category, version) == {
        "accept_insiderEula": True,
        "select": "Latest",
        "storageAccount": "bcinsider",
    }


def test_data_query_always_uses_insider_artifacts():
    assert get_artifact_config("data-query", "28.0") == {
        "accept_insiderEula": True,
        "select": "Latest",
        "storageAccount": "bcinsider",
    }


def test_setup_workflow_passes_resolved_version_to_artifact_config():
    action = (ROOT / ".github" / "actions" / "setup-bc-container-repo" / "action.yml").read_text(encoding="utf-8")
    setup_script = (ROOT / "scripts" / "Setup-ContainerAndRepository.ps1").read_text(encoding="utf-8")
    utils_module = UTILS_MODULE.read_text(encoding="utf-8")

    assert 'Get-BCBenchArtifactConfig -Category "${{ inputs.category }}" -Version $version' in action
    assert "Get-BCBenchArtifactConfig -Category $Category -Version $Version" in setup_script
    assert "'App/Internal/Apps'" in utils_module
