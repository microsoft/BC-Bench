import re
from pathlib import Path
from typing import get_args

from bcbench.cli_options import CopilotModel

REPO_ROOT = Path(__file__).parents[1]


def _workflow_dispatch_model_choices(workflow: str) -> set[str]:
    choices: set[str] = set()
    in_model_options = False

    for line in workflow.splitlines():
        if re.match(r"^\s*model:\s*$", line):
            in_model_options = True
            continue
        if in_model_options and re.match(r"^\s*category:\s*$", line):
            break
        if in_model_options:
            match = re.match(r'^\s*-\s*"([^"]+)"\s*$', line)
            if match:
                choices.add(match.group(1))

    assert choices
    return choices


def test_copilot_workflow_model_choices_are_supported_by_cli():
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "copilot-evaluation.yml"
    ).read_text(encoding="utf-8")
    workflow_choices = _workflow_dispatch_model_choices(workflow)
    cli_choices = set(get_args(get_args(CopilotModel)[0]))
    assert workflow_choices <= cli_choices


def test_copilot_harness_supports_gpt_5_6():
    installer = (
        REPO_ROOT / ".github" / "actions" / "install-eval-clis" / "action.yml"
    ).read_text(encoding="utf-8")
    version_match = re.search(r"@github/copilot@(\d+)\.(\d+)\.(\d+)", installer)
    assert version_match is not None
    assert tuple(map(int, version_match.groups())) >= (1, 0, 70)
