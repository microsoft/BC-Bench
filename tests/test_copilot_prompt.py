from pathlib import Path
from unittest.mock import patch

from bcbench.agent.copilot.prompt import build_prompt
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry, create_problem_statement_dir


def test_build_prompt_without_project_paths(tmp_path: Path):
    entry = create_dataset_entry(
        instance_id="microsoftInternal__NAV-1",
        project_paths=["App/Apps/W1/Payment/app", "App/Apps/W1/Payment/test"],
    )
    repo_path = tmp_path / "navapp"
    repo_path.mkdir()
    problem_dir = create_problem_statement_dir(tmp_path, "Fix the bug in the payment module\n\nCheck the validation logic")

    config = {
        "prompt": {
            "bug-fix-template": "Working at {{repo_path}}. Task: {{task}}",
            "include_project_paths": False,
        }
    }

    with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
        result = build_prompt(entry, repo_path, config, EvaluationCategory.BUG_FIX)

    assert "Working at" in result
    assert "navapp" in result
    assert "Fix the bug in the payment module" in result
    assert "Check the validation logic" in result
    assert "Payment" not in result  # project paths not included


def test_build_prompt_with_project_paths(tmp_path: Path):
    entry = create_dataset_entry(
        instance_id="microsoftInternal__NAV-2",
        project_paths=["App/Apps/W1/Sales/app", "App/Apps/W1/Inventory/app"],
    )
    repo_path = tmp_path / "navapp"
    repo_path.mkdir()
    problem_dir = create_problem_statement_dir(tmp_path, "Update the sales calculation")

    config = {
        "prompt": {
            "bug-fix-template": "Repo: {{repo_path}}. {% if include_project_paths %}Projects: {{project_paths}}{% endif %}. Task: {{task}}",
            "include_project_paths": True,
        }
    }

    with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
        result = build_prompt(entry, repo_path, config, EvaluationCategory.BUG_FIX)

    assert "navapp" in result
    assert "App/Apps/W1/Sales/app, App/Apps/W1/Inventory/app" in result
    assert "Update the sales calculation" in result
