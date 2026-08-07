"""
Simple tests for agent skills setup and operations.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest

from bcbench.dataset import BaseDatasetEntry, RepoGroundedEntry
from bcbench.operations import setup_agent_skills
from bcbench.operations.instruction_operations import _get_source_instructions_path
from bcbench.types import AgentType


def test_setup_agent_skills_path():
    path = _get_source_instructions_path("microsoftInternal-NAV")
    assert path.exists(), f"Skills path should exist: {path}"
    assert path.name == "microsoftInternal-NAV"


def test_setup_agent_skills():
    skills_source = _get_source_instructions_path("microsoftInternal-NAV") / "skills"

    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=RepoGroundedEntry)
        entry.customization_profile = "microsoftInternal-NAV"
        config = {"skills": {"enabled": True}}

        # Setup skills
        result = setup_agent_skills(config, entry, repo_path, agent_type=AgentType.COPILOT)
        assert result is True

        # Verify
        target_path = repo_path / ".github" / "skills"
        assert target_path.exists(), ".github/skills directory should be created"

        # Verify files were copied
        for item in skills_source.iterdir():
            target_item = target_path / item.name
            assert target_item.exists(), f"{target_item} should exist"

            # Verify file content matches
            if item.is_file():
                assert target_item.read_text() == item.read_text(), f"Content mismatch for {item.name}"
            elif item.is_dir():
                # For directories, verify all files match recursively
                for source_file in item.rglob("*"):
                    if source_file.is_file():
                        target_file = target_item / source_file.relative_to(item)
                        assert target_file.exists(), f"{target_file} should exist"
                        assert target_file.read_text() == source_file.read_text(), f"Content mismatch for {target_file}"


def test_nonexistent_skills():
    """Test that setup_agent_skills raises FileNotFoundError for nonexistent profile."""
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=RepoGroundedEntry)
        entry.customization_profile = "nonexistent-repo"
        config = {"skills": {"enabled": True}}

        # Error comes from _get_source_instructions_path when the profile folder doesn't exist
        with pytest.raises(FileNotFoundError, match="not found"):
            setup_agent_skills(config, entry, repo_path, agent_type=AgentType.COPILOT)


def test_overwrite_skill_folder_files():
    """
    When a skill folder already exists:
    - same-named files should be overwritten
    - unrelated files should be removed (replace semantics)
    """
    skills_source = _get_source_instructions_path("microsoftInternal-NAV") / "skills"
    source_skill_dir = skills_source / "al-test-generation"

    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=RepoGroundedEntry)
        entry.customization_profile = "microsoftInternal-NAV"
        config = {"skills": {"enabled": True}}

        # Target skill folder
        target_skill_dir = repo_path / ".github" / "skills" / "al-test-generation"
        target_skill_dir.mkdir(parents=True, exist_ok=True)

        # 1. Create conflicting file (same name, different content)
        source_file = source_skill_dir / "SKILL.md"
        target_file = target_skill_dir / "SKILL.md"
        target_file.write_text("OLD CONTENT")

        # 2. Create unrelated file (should be removed with replace semantics)
        extra_file = target_skill_dir / "EXTRA.md"
        extra_file.write_text("SHOULD BE REMOVED")

        # Run setup
        setup_agent_skills(config, entry, repo_path, agent_type=AgentType.COPILOT)

        # Assert overwrite happened
        assert target_file.read_text() == source_file.read_text()

        # Assert unrelated file was removed (replace semantics)
        assert not extra_file.exists(), "Unrelated files should be removed with replace semantics"


def test_path_specific_skills_copied():
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=RepoGroundedEntry)
        entry.customization_profile = "microsoftInternal-NAV"
        config = {"skills": {"enabled": True}}

        # Setup skills
        setup_agent_skills(config, entry, repo_path, agent_type=AgentType.COPILOT)

        # Verify path-specific skills were copied
        target_skills_dir = repo_path / ".github" / "skills"
        assert target_skills_dir.exists(), "Skills folder should be created"

        # Verify that at least some skill files exist
        sample_skill_file = target_skills_dir / "al-test-generation" / "SKILL.md"
        assert sample_skill_file.exists(), "Sample skill file should exist"


def test_path_specific_skills_removed_before_copy():
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=RepoGroundedEntry)
        entry.customization_profile = "microsoftInternal-NAV"
        config = {"skills": {"enabled": True}}

        # Create existing .github/skills directory with old files
        skills_dir = repo_path / ".github" / "skills" / "al-test-generation"
        skills_dir.mkdir(parents=True, exist_ok=True)
        old_file = skills_dir / "OLD_SKILL.md"
        old_file.write_text("OLD SKILL CONTENT")

        # Setup skills
        setup_agent_skills(config, entry, repo_path, agent_type=AgentType.COPILOT)

        # Verify old file was removed
        assert not old_file.exists(), "Old skill file should be removed"

        # Verify new skill file exists
        new_skill_file = repo_path / ".github" / "skills" / "al-test-generation" / "SKILL.md"
        assert new_skill_file.exists(), "New skill file should exist"


def test_skills_disabled():
    """When skills disabled, should return False and not create directory."""
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=RepoGroundedEntry)
        entry.customization_profile = "microsoftInternal-NAV"
        config = {"skills": {"enabled": False}}

        result = setup_agent_skills(config, entry, repo_path, agent_type=AgentType.COPILOT)

        assert result is False
        assert not (repo_path / ".github" / "skills").exists()


def test_skills_override_enables_when_config_disabled():
    """--skills (override=True) enables skills even when config.yaml has them disabled."""
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=BaseDatasetEntry)
        entry.customization_profile = "microsoftInternal-NAV"
        config = {"skills": {"enabled": False}}

        result = setup_agent_skills(config, entry, repo_path, agent_type=AgentType.COPILOT, skills_enabled_override=True)

        assert result is True
        assert (repo_path / ".github" / "skills").exists()


def test_skills_override_disables_when_config_enabled():
    """override=False wins over an enabled config, so no skills are copied."""
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=BaseDatasetEntry)
        entry.customization_profile = "microsoftInternal-NAV"
        config = {"skills": {"enabled": True}}

        result = setup_agent_skills(config, entry, repo_path, agent_type=AgentType.COPILOT, skills_enabled_override=False)

        assert result is False
        assert not (repo_path / ".github" / "skills").exists()


def test_skills_override_none_falls_back_to_config():
    """override=None (default) preserves the config-driven behavior."""
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=BaseDatasetEntry)
        entry.customization_profile = "microsoftInternal-NAV"
        config = {"skills": {"enabled": False}}

        result = setup_agent_skills(config, entry, repo_path, agent_type=AgentType.COPILOT, skills_enabled_override=None)

        assert result is False
        assert not (repo_path / ".github" / "skills").exists()
