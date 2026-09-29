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


@pytest.mark.parametrize(
    ("version", "url"),
    [
        ("29.0", "https://bcinsider-fvh2ekdjecfjd6gk.b02.azurefd.net/sandbox/29.0.54011.55007/w1"),
        ("30.0", "https://bcinsider-fvh2ekdjecfjd6gk.b02.azurefd.net/sandbox/30.0.55015.0/w1"),
    ],
)
def test_insider_bug_fix_uses_pinned_artifact(version: str, url: str):
    assert get_artifact_config("bug-fix", version) == {
        "accept_insiderEula": True,
        "artifactUrl": url,
    }


def test_setup_paths_cover_internal_apps():
    utils_module = UTILS_MODULE.read_text(encoding="utf-8")

    assert "'App/Internal/Apps'" in utils_module
