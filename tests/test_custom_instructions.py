from pathlib import Path

import pytest

from bcbench.dataset import BugFixEntry
from bcbench.operations.instruction_operations import INSTRUCTION_SOURCE_FILE, instructions_profile_dir, setup_custom_agent, setup_instructions_from_config
from bcbench.types import CustomAgentsConfig, EvaluationCategory, ToggleConfig

ENABLED = ToggleConfig(enabled=True)


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    source = tmp_path / "profile"
    (source / "instructions").mkdir(parents=True)
    (source / INSTRUCTION_SOURCE_FILE).write_text("# Repo instructions", encoding="utf-8")
    (source / "instructions" / "al.instructions.md").write_text("# AL rules", encoding="utf-8")
    (source / "agents").mkdir()
    (source / "agents" / "al-dev.agent.md").write_text("# AL developer", encoding="utf-8")
    return source


@pytest.fixture
def target_dir(tmp_path: Path) -> Path:
    return tmp_path / "repo" / ".github"


def test_shipped_profile_exists():
    assert instructions_profile_dir("microsoftInternal-NAV").is_dir()


def test_instructions_are_copied_with_the_agent_specific_file_name(source_dir, target_dir):
    assert setup_instructions_from_config(ENABLED, source_dir, target_dir, "CLAUDE.md") is True

    assert (target_dir / "CLAUDE.md").read_text(encoding="utf-8") == "# Repo instructions"
    assert not (target_dir / INSTRUCTION_SOURCE_FILE).exists()
    assert (target_dir / "instructions" / "al.instructions.md").read_text(encoding="utf-8") == "# AL rules"


def test_instructions_replace_the_existing_target(source_dir, target_dir):
    target_dir.mkdir(parents=True)
    (target_dir / "old.md").write_text("stale", encoding="utf-8")
    (target_dir / "copilot-instructions.md").write_text("stale", encoding="utf-8")

    setup_instructions_from_config(ENABLED, source_dir, target_dir, "copilot-instructions.md")

    assert not (target_dir / "old.md").exists()
    assert (target_dir / "copilot-instructions.md").read_text(encoding="utf-8") == "# Repo instructions"


def test_disabled_instructions_leave_the_target_untouched(tmp_path, target_dir):
    assert setup_instructions_from_config(ToggleConfig(), tmp_path / "missing", target_dir, "CLAUDE.md") is False
    assert not target_dir.exists()


def test_enabled_instructions_require_the_source_folder(tmp_path, target_dir):
    with pytest.raises(FileNotFoundError, match="missing"):
        setup_instructions_from_config(ENABLED, tmp_path / "missing", target_dir, "CLAUDE.md")


def test_custom_agents_are_copied_and_named(source_dir, target_dir):
    agent = setup_custom_agent(CustomAgentsConfig(enabled=True, name="al-dev"), source_dir, target_dir)

    assert agent == "al-dev"
    assert (target_dir / "agents" / "al-dev.agent.md").is_file()


def test_disabled_custom_agents_are_not_copied(source_dir, target_dir):
    assert setup_custom_agent(CustomAgentsConfig(name="al-dev"), source_dir, target_dir) is None
    assert not target_dir.exists()


def test_repo_grounded_profile_is_derived_from_repo():
    test_cases = [
        ("microsoftInternal/NAV", "microsoftInternal-NAV"),
        ("org/repo", "org-repo"),
        ("user/my-repo", "user-my-repo"),
    ]

    for repo_name, expected_profile in test_cases:
        entry = BugFixEntry.model_construct(repo=repo_name)
        assert entry.customization_profile == expected_profile, f"Failed for {repo_name}"


def test_every_category_entry_class_names_a_customization_profile():
    for category in EvaluationCategory:
        entry = category.entry_class.model_construct(repo="microsoft/BCApps")
        assert entry.customization_profile, f"{category} has no customization profile"
