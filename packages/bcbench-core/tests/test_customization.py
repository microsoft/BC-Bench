from pathlib import Path

import pytest

from bcbench_core.agent.customization import INSTRUCTION_SOURCE_FILE, CustomAgentsConfig, ToggleConfig, setup_custom_agent, setup_instructions, setup_skills

ENABLED = ToggleConfig(enabled=True)


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    source = tmp_path / "profile"
    (source / "instructions").mkdir(parents=True)
    (source / INSTRUCTION_SOURCE_FILE).write_text("# Repo instructions", encoding="utf-8")
    (source / "instructions" / "al.instructions.md").write_text("# AL rules", encoding="utf-8")
    (source / "agents").mkdir()
    (source / "agents" / "al-dev.agent.md").write_text("# AL developer", encoding="utf-8")
    (source / "skills" / "al-test-generation").mkdir(parents=True)
    (source / "skills" / "al-test-generation" / "SKILL.md").write_text("# Generate AL tests", encoding="utf-8")
    return source


@pytest.fixture
def target_dir(tmp_path: Path) -> Path:
    return tmp_path / "repo" / ".github"


class TestInstructions:
    def test_are_copied_with_the_agent_specific_file_name(self, source_dir, target_dir):
        assert setup_instructions(ENABLED, source_dir, target_dir, "CLAUDE.md") is True

        assert (target_dir / "CLAUDE.md").read_text(encoding="utf-8") == "# Repo instructions"
        assert not (target_dir / INSTRUCTION_SOURCE_FILE).exists()
        assert (target_dir / "instructions" / "al.instructions.md").read_text(encoding="utf-8") == "# AL rules"

    def test_replace_the_existing_target(self, source_dir, target_dir):
        target_dir.mkdir(parents=True)
        (target_dir / "old.md").write_text("stale", encoding="utf-8")
        (target_dir / "copilot-instructions.md").write_text("stale", encoding="utf-8")

        setup_instructions(ENABLED, source_dir, target_dir, "copilot-instructions.md")

        assert not (target_dir / "old.md").exists()
        assert (target_dir / "copilot-instructions.md").read_text(encoding="utf-8") == "# Repo instructions"

    def test_disabled_leave_the_target_untouched(self, tmp_path, target_dir):
        assert setup_instructions(ToggleConfig(), tmp_path / "missing", target_dir, "CLAUDE.md") is False
        assert not target_dir.exists()

    def test_enabled_require_the_source_folder(self, tmp_path, target_dir):
        with pytest.raises(FileNotFoundError, match="missing"):
            setup_instructions(ENABLED, tmp_path / "missing", target_dir, "CLAUDE.md")


class TestSkills:
    def test_are_copied(self, source_dir, target_dir):
        assert setup_skills(ENABLED, source_dir, target_dir) is True

        assert (target_dir / "skills" / "al-test-generation" / "SKILL.md").read_text(encoding="utf-8") == "# Generate AL tests"

    def test_replace_existing_skills_but_keep_the_rest_of_the_target(self, source_dir, target_dir):
        stale_skill = target_dir / "skills" / "al-test-generation"
        stale_skill.mkdir(parents=True)
        (stale_skill / "SKILL.md").write_text("OLD", encoding="utf-8")
        (stale_skill / "EXTRA.md").write_text("OLD", encoding="utf-8")
        (target_dir / "copilot-instructions.md").write_text("# Keep", encoding="utf-8")

        setup_skills(ENABLED, source_dir, target_dir)

        assert (stale_skill / "SKILL.md").read_text(encoding="utf-8") == "# Generate AL tests"
        assert not (stale_skill / "EXTRA.md").exists()
        assert (target_dir / "copilot-instructions.md").exists()

    def test_disabled_are_not_copied(self, tmp_path, target_dir):
        assert setup_skills(ToggleConfig(), tmp_path / "missing", target_dir) is False
        assert not target_dir.exists()

    def test_enabled_require_the_skills_folder(self, tmp_path, target_dir):
        with pytest.raises(FileNotFoundError, match="skills"):
            setup_skills(ENABLED, tmp_path / "missing", target_dir)


class TestCustomAgents:
    def test_are_copied_and_named(self, source_dir, target_dir):
        agent = setup_custom_agent(CustomAgentsConfig(enabled=True, name="al-dev"), source_dir, target_dir)

        assert agent == "al-dev"
        assert (target_dir / "agents" / "al-dev.agent.md").is_file()

    def test_disabled_are_not_copied(self, source_dir, target_dir):
        assert setup_custom_agent(CustomAgentsConfig(name="al-dev"), source_dir, target_dir) is None
        assert not target_dir.exists()

    def test_enabled_require_the_agents_folder(self, tmp_path, target_dir):
        with pytest.raises(FileNotFoundError, match="agents"):
            setup_custom_agent(CustomAgentsConfig(enabled=True, name="al-dev"), tmp_path / "missing", target_dir)


def test_config_rejects_unknown_keys():
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        ToggleConfig.model_validate({"enabled": True, "enable": True})
