from pathlib import Path

import pytest

from bcbench.operations import setup_agent_skills
from bcbench.types import ToggleConfig

ENABLED = ToggleConfig(enabled=True)


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    skill = tmp_path / "profile" / "skills" / "al-test-generation"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Generate AL tests", encoding="utf-8")
    return tmp_path / "profile"


@pytest.fixture
def target_dir(tmp_path: Path) -> Path:
    return tmp_path / "repo" / ".github"


def test_skills_are_copied(source_dir, target_dir):
    assert setup_agent_skills(ENABLED, source_dir, target_dir) is True

    assert (target_dir / "skills" / "al-test-generation" / "SKILL.md").read_text(encoding="utf-8") == "# Generate AL tests"


def test_skills_replace_existing_skills_but_keep_the_rest_of_the_target(source_dir, target_dir):
    stale_skill = target_dir / "skills" / "al-test-generation"
    stale_skill.mkdir(parents=True)
    (stale_skill / "SKILL.md").write_text("OLD", encoding="utf-8")
    (stale_skill / "EXTRA.md").write_text("OLD", encoding="utf-8")
    (target_dir / "copilot-instructions.md").write_text("# Keep", encoding="utf-8")

    setup_agent_skills(ENABLED, source_dir, target_dir)

    assert (stale_skill / "SKILL.md").read_text(encoding="utf-8") == "# Generate AL tests"
    assert not (stale_skill / "EXTRA.md").exists()
    assert (target_dir / "copilot-instructions.md").exists()


def test_disabled_skills_are_not_copied(tmp_path, target_dir):
    assert setup_agent_skills(ToggleConfig(), tmp_path / "missing", target_dir) is False
    assert not target_dir.exists()


def test_enabled_skills_require_the_skills_folder(tmp_path, target_dir):
    with pytest.raises(FileNotFoundError, match="skills"):
        setup_agent_skills(ENABLED, tmp_path / "missing", target_dir)
