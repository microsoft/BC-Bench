from pathlib import Path

from bcbench.agent.copilot.copilot_agent import _build_prompt
from bcbench.dataset import DatasetEntry


def test_build_prompt_without_project_paths():
    entry = DatasetEntry(
        instance_id="test_instance_1",
        repo="microsoft/navapp",
        base_commit="abc123",
        problem_statement="Fix the bug in the payment module",
        hints_text="Check the validation logic",
        project_paths=["App/Apps/W1/Payment/app"],
    )
    repo_path = Path("C:/testbed/navapp")
    config = {
        "agent": {
            "prompt": {
                "template": "Working at {{repo_path}}. Task: {{task}}",
                "include_project_paths": False,
            }
        }
    }

    result = _build_prompt(entry, repo_path, config)

    assert "Working at C:" in result or "Working at C:/" in result
    assert "testbed" in result
    assert "navapp" in result
    assert "Fix the bug in the payment module" in result
    assert "Check the validation logic" in result
    assert "Payment" not in result  # project paths not included


def test_build_prompt_with_project_paths():
    entry = DatasetEntry(
        instance_id="test_instance_2",
        repo="microsoft/navapp",
        base_commit="def456",
        problem_statement="Update the sales calculation",
        project_paths=["App/Apps/W1/Sales/app", "App/Apps/W1/Inventory/app"],
    )
    repo_path = Path("/workspace/navapp")
    config = {
        "agent": {
            "prompt": {
                "template": "Repo: {{repo_path}}. {% if include_project_paths %}Projects: {{project_paths}}{% endif %}. Task: {{task}}",
                "include_project_paths": True,
            }
        }
    }

    result = _build_prompt(entry, repo_path, config)

    assert "workspace" in result and "navapp" in result
    assert "App/Apps/W1/Sales/app, App/Apps/W1/Inventory/app" in result
    assert "Update the sales calculation" in result


def test_build_prompt_empty_project_paths():
    entry = DatasetEntry(
        instance_id="test_instance_5",
        repo="microsoft/navapp",
        base_commit="mno345",
        problem_statement="Fix issue",
        project_paths=[],
    )
    repo_path = Path("/var/repo")
    config = {
        "agent": {
            "prompt": {
                "template": "{% if include_project_paths %}Projects: {{project_paths}}{% endif %}Task: {{task}}",
                "include_project_paths": True,
            }
        }
    }

    result = _build_prompt(entry, repo_path, config)

    assert "Task: Fix issue" in result
    assert "Projects:" in result
