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


def test_released_bug_fix_uses_pinned_artifact():
    assert get_artifact_config("bug-fix", "27.2") == {
        "accept_insiderEula": False,
        "artifactUrl": "https://bcartifacts-exdbf9fwegejdqak.b02.azurefd.net/sandbox/27.2.42879.54576/w1",
    }


def test_unpinned_bug_fix_version_fails():
    with pytest.raises(subprocess.CalledProcessError):
        get_artifact_config("bug-fix", "28.0")


def test_setup_workflow_passes_resolved_version_to_artifact_config():
    action = (ROOT / ".github" / "actions" / "setup-bc-container-repo" / "action.yml").read_text(encoding="utf-8")
    setup_script = (ROOT / "scripts" / "Setup-ContainerAndRepository.ps1").read_text(encoding="utf-8")
    utils_module = UTILS_MODULE.read_text(encoding="utf-8")

    assert '$url = (Get-BCBenchArtifactConfig -Version $version -Category "${{ inputs.category }}").artifactUrl' in action
    assert "Get-BCBenchArtifactConfig -Category $Category -Version $Version -Country $Country" in setup_script
    assert "'App/Internal/Apps'" in utils_module
