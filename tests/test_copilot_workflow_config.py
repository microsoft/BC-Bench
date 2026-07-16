import re
from pathlib import Path
from typing import get_args

import pytest
import yaml

from bcbench.cli_options import CopilotModel

REPO_ROOT = Path(__file__).parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "copilot-evaluation.yml"


def _workflow_dispatch_model_choices(
    workflow_path: Path | str = WORKFLOW_PATH,
) -> set[str]:
    workflow = yaml.load(
        Path(workflow_path).read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    choices = workflow["on"]["workflow_dispatch"]["inputs"]["model"]["options"]
    assert choices, "Copilot workflow model options must not be empty"
    return {str(choice) for choice in choices}


def test_workflow_dispatch_model_choices_reject_empty_options(tmp_path: Path):
    workflow_path = tmp_path / "copilot-evaluation.yml"
    workflow_path.write_text(
        """
on:
  workflow_dispatch:
    inputs:
      model:
        type: choice
        options: []
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="Copilot workflow model options must not be empty"):
        _workflow_dispatch_model_choices(workflow_path)


def test_workflow_dispatch_model_choices_ignore_other_inputs(tmp_path: Path):
    workflow_path = tmp_path / "copilot-evaluation.yml"
    workflow_path.write_text(
        """
on:
  workflow_dispatch:
    inputs:
      category:
        type: choice
        options:
          - bug-fix
          - test-generation
      model:
        type: choice
        options:
          - gpt-5.6-sol
          - gpt-5.4
      retries:
        type: choice
        options:
          - "1"
          - "2"
""".lstrip(),
        encoding="utf-8",
    )

    assert _workflow_dispatch_model_choices(workflow_path) == {
        "gpt-5.6-sol",
        "gpt-5.4",
    }


def test_copilot_workflow_includes_gpt_5_6_sol():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert '- "gpt-5.6-sol"' in workflow


def test_copilot_workflow_model_choices_are_supported_by_cli():
    workflow_choices = _workflow_dispatch_model_choices()
    cli_choices = set(get_args(get_args(CopilotModel)[0]))
    assert workflow_choices <= cli_choices


def test_copilot_harness_supports_gpt_5_6():
    installer = (REPO_ROOT / ".github" / "actions" / "install-eval-clis" / "action.yml").read_text(encoding="utf-8")
    version_match = re.search(r"@github/copilot@(\d+)\.(\d+)\.(\d+)", installer)
    assert version_match is not None
    assert tuple(map(int, version_match.groups())) >= (1, 0, 70)
