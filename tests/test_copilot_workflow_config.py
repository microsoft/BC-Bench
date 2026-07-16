import re
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]


def test_copilot_workflow_exposes_gpt_5_6_sol():
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "copilot-evaluation.yml"
    ).read_text(encoding="utf-8")
    assert '- "gpt-5.6-sol"' in workflow


def test_copilot_harness_supports_gpt_5_6():
    installer = (
        REPO_ROOT / ".github" / "actions" / "install-eval-clis" / "action.yml"
    ).read_text(encoding="utf-8")
    version_match = re.search(r"@github/copilot@(\d+)\.(\d+)\.(\d+)", installer)
    assert version_match is not None
    assert tuple(map(int, version_match.groups())) >= (1, 0, 70)
