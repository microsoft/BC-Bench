from pathlib import Path
from unittest.mock import patch

import yaml

from bcbench.agent.shared import build_prompt
from bcbench.config import get_config
from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry, create_ext_advisor_entry, create_problem_statement_dir


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


def test_bug_fix_experiment_uses_fix_bug_custom_agent():
    config_path = get_config().paths.agent_share_dir / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert config["skills"]["enabled"] is False
    assert config["agents"] == {"enabled": True, "name": "fix-bug"}


def test_bug_fix_prompt_does_not_explicitly_select_skill(tmp_path: Path):
    config_path = get_config().paths.agent_share_dir / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    entry = create_dataset_entry(
        instance_id="microsoftInternal__NAV-999",
        project_paths=["App/Layers/W1/BaseApp"],
    )
    problem_dir = create_problem_statement_dir(tmp_path, "Fix the reported bug")

    with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
        prompt = build_prompt(entry, tmp_path, config, EvaluationCategory.BUG_FIX)

    assert "bc-fix-bug" not in prompt


def test_build_prompt_test_generation_gold_patch_mode(tmp_path: Path):
    entry = create_dataset_entry(
        instance_id="microsoftInternal__NAV-3",
        project_paths=["App/Apps/W1/Payment/app", "App/Apps/W1/Payment/test"],
    )
    repo_path = tmp_path / "navapp"
    repo_path.mkdir()
    problem_dir = create_problem_statement_dir(tmp_path, "Fix payment validation bug")

    config = {
        "prompt": {
            "test-generation-template": "Repo: {{repo_path}}. {% if is_gold_patch %}Generate test for fix{% else %}Generate test for issue: {{task}}{% endif %}",
            "test-generation-input": "gold-patch",
            "include_project_paths": False,
        }
    }

    with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
        result = build_prompt(entry, repo_path, config, EvaluationCategory.TEST_GENERATION)

    assert "navapp" in result
    assert "Generate test for fix" in result
    assert "Fix payment validation bug" not in result  # task should not be included in gold-patch mode


def test_build_prompt_test_generation_problem_statement_mode(tmp_path: Path):
    entry = create_dataset_entry(
        instance_id="microsoftInternal__NAV-4",
        project_paths=["App/Apps/W1/Payment/app", "App/Apps/W1/Payment/test"],
    )
    repo_path = tmp_path / "navapp"
    repo_path.mkdir()
    problem_dir = create_problem_statement_dir(tmp_path, "Fix payment validation bug")

    config = {
        "prompt": {
            "test-generation-template": "Repo: {{repo_path}}. {% if is_gold_patch %}Generate test for fix{% else %}Generate test for issue: {{task}}{% endif %}",
            "test-generation-input": "problem-statement",
            "include_project_paths": False,
        }
    }

    with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
        result = build_prompt(entry, repo_path, config, EvaluationCategory.TEST_GENERATION)

    assert "navapp" in result
    assert "Generate test for issue:" in result
    assert "Fix payment validation bug" in result  # task should be included in problem-statement mode


def test_build_prompt_test_generation_both_mode(tmp_path: Path):
    entry = create_dataset_entry(
        instance_id="microsoftInternal__NAV-5",
        project_paths=["App/Apps/W1/Payment/app", "App/Apps/W1/Payment/test"],
    )
    repo_path = tmp_path / "navapp"
    repo_path.mkdir()
    problem_dir = create_problem_statement_dir(tmp_path, "Fix payment validation bug")

    config = {
        "prompt": {
            "test-generation-template": "Repo: {{repo_path}}. {% if is_gold_patch %}[HAS_PATCH]{% endif %}{% if is_problem_statement %}[HAS_ISSUE] {{task}}{% endif %}",
            "test-generation-input": "both",
            "include_project_paths": False,
        }
    }

    with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
        result = build_prompt(entry, repo_path, config, EvaluationCategory.TEST_GENERATION)

    assert "navapp" in result
    assert "[HAS_PATCH]" in result  # gold patch should be indicated
    assert "[HAS_ISSUE]" in result  # problem statement should be indicated
    assert "Fix payment validation bug" in result  # task should be included in both mode


def test_build_prompt_code_review_enforces_review_json_contract(tmp_path: Path):
    config_path = get_config().paths.agent_share_dir / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    entry = CodeReviewEntry.model_construct(project_paths=[], patch="diff --git a/src/Foo.al b/src/Foo.al")

    prompt = build_prompt(entry, tmp_path, config, EvaluationCategory.CODE_REVIEW)

    assert "staged and unstaged dataset changes" in prompt
    assert "git diff HEAD" in prompt
    assert "Do NOT modify source code" in prompt
    assert f"`{tmp_path}/review.json`" in prompt
    assert "one JSON array" in prompt
    for field in ("file", "line_start", "line_end", "domain", "body", "severity"):
        assert f"`{field}`" in prompt
    assert "empty array" in prompt


def test_build_prompt_ext_advisor_delegates_to_custom_agent(tmp_path: Path):
    config_path = get_config().paths.agent_share_dir / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    prompt = build_prompt(
        create_ext_advisor_entry(),
        tmp_path,
        config,
        EvaluationCategory.EXT_REQUEST_ADVISOR,
    )

    assert "advisor_result.json" in prompt
    assert "Extensibility scenario:" in prompt
    assert "Codeunit 5880" in prompt
    assert len(prompt.splitlines()) < 15
