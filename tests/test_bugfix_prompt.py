from pathlib import Path
from unittest.mock import patch

import yaml

from bcbench.agent.shared import build_prompt
from bcbench.config import get_config
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry, create_problem_statement_dir


def load_shared_config() -> dict:
    config_file: Path = get_config().paths.agent_share_dir / "config.yaml"
    return yaml.safe_load(config_file.read_text(encoding="utf-8"))


def render(tmp_path: Path, *, al_mcp: bool = False, skills_enabled: bool = False) -> str:
    entry = create_dataset_entry(instance_id="microsoftInternal__NAV-9")
    repo_path = tmp_path / "navapp"
    repo_path.mkdir(exist_ok=True)
    problem_dir = create_problem_statement_dir(tmp_path, "Quantity may go negative")

    config = load_shared_config()
    config["skills"]["enabled"] = skills_enabled

    with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)):
        return build_prompt(entry, repo_path, config, EvaluationCategory.BUG_FIX, al_mcp=al_mcp)


def test_prompt_requires_a_reproducing_test_first(tmp_path):
    prompt = render(tmp_path)

    assert "test-first" in prompt.lower()
    assert "reproduces the issue" in prompt
    assert "Quantity may go negative" in prompt


def test_prompt_no_longer_forbids_touching_tests(tmp_path):
    prompt = render(tmp_path)

    assert "Do NOT modify any testing logic" not in prompt


def test_prompt_asks_for_red_green_when_al_mcp_is_on(tmp_path):
    prompt = render(tmp_path, al_mcp=True)

    assert "confirm it fails before the fix and passes after" in prompt
    assert "Do NOT try to build or run tests" not in prompt


def test_prompt_forbids_building_when_al_mcp_is_off(tmp_path):
    prompt = render(tmp_path, al_mcp=False)

    assert "Do NOT try to build or run tests" in prompt


def test_prompt_nudges_the_skill_only_when_skills_are_enabled(tmp_path):
    assert "bc-fix-bug" in render(tmp_path, skills_enabled=True)
    assert "bc-fix-bug" not in render(tmp_path, skills_enabled=False)


def test_prompt_places_the_test_in_the_existing_test_project(tmp_path):
    prompt = render(tmp_path)

    assert "existing" in prompt.lower()
    assert "test project" in prompt.lower()
    assert "never in an application project" in prompt.lower()


def test_prompt_warns_that_extra_tests_break_the_run(tmp_path):
    prompt = render(tmp_path)

    assert "exactly ONE" in prompt
    assert "run together" in prompt
