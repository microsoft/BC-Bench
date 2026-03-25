"""
Simple verification script for custom instructions framework.
Verifies that instruction files get created without invoking the copilot agent.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.operations.instruction_operations import (
    _get_source_instructions_path,
    setup_instructions_from_config,
)
from bcbench.types import AgentType

_config = get_config()


def test_get_instructions_path():
    # Test with microsoftInternal/NAV
    path = _get_source_instructions_path("microsoftInternal/NAV")
    assert path.exists(), f"Instruction file should exist: {path}"
    assert path.name == "microsoftInternal-NAV"


def test_setup_custom_instructions():
    instructions_source = _get_source_instructions_path("microsoftInternal/NAV")

    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=DatasetEntry)
        entry.repo = "microsoftInternal/NAV"
        config = {"instructions": {"enabled": True}}

        # Setup instructions
        result = setup_instructions_from_config(config, entry, repo_path, agent_type=AgentType.COPILOT)
        assert result is True

        # Verify
        target_path = repo_path / ".github"
        assert target_path.exists(), ".github directory should be created"

        # Verify files were copied (AGENTS.md gets renamed to agent-specific filename)
        source_naming = _config.file_patterns.instruction_source_naming
        for item in instructions_source.iterdir():
            target_item = target_path / AgentType.COPILOT.instruction_filename if item.name == source_naming else target_path / item.name
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
                        assert target_file.read_text(encoding="utf-8") == source_file.read_text(encoding="utf-8"), f"Content mismatch for {target_file}"


def test_sanitization():
    test_cases = [
        ("microsoftInternal/NAV", "microsoftInternal-NAV"),
        ("org/repo", "org-repo"),
        ("user/my-repo", "user-my-repo"),
    ]

    for repo_name, expected_sanitized in test_cases:
        sanitized = repo_name.replace("/", "-")
        assert sanitized == expected_sanitized, f"Failed for {repo_name}"


def test_nonexistent_instructions():
    try:
        _get_source_instructions_path("nonexistent/repo")
        raise AssertionError("Should raise FileNotFoundError")
    except FileNotFoundError as e:
        assert "nonexistent/repo" in str(e)


def test_overwrite_existing_instructions():
    instructions_source = _get_source_instructions_path("microsoftInternal/NAV")

    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=DatasetEntry)
        entry.repo = "microsoftInternal/NAV"
        config = {"instructions": {"enabled": True}}

        # Create initial instruction file with different content
        github_dir = repo_path / ".github"
        github_dir.mkdir(parents=True, exist_ok=True)
        target_path = github_dir / AgentType.COPILOT.instruction_filename
        original_content = "# Original instructions\nThis should be overwritten"
        target_path.write_text(original_content)

        # Setup instructions (should overwrite)
        setup_instructions_from_config(config, entry, repo_path, agent_type=AgentType.COPILOT)

        # Verify file was overwritten
        assert target_path.exists(), "Instruction file should exist"
        new_content = target_path.read_text(encoding="utf-8")
        assert new_content != original_content, "Content should be overwritten"
        source_file = instructions_source / _config.file_patterns.instruction_source_naming
        assert new_content == source_file.read_text(encoding="utf-8"), "Content should match source"


def test_path_specific_instructions_removed_before_copy():
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=DatasetEntry)
        entry.repo = "microsoftInternal/NAV"
        config = {"instructions": {"enabled": True}}

        # Create existing .github directory with old files
        github_dir = repo_path / ".github"
        github_dir.mkdir(parents=True, exist_ok=True)
        old_file = github_dir / "old.md"
        old_file.write_text("# Old instruction that should be removed")

        # Setup instructions (should remove existing .github and copy new one)
        setup_instructions_from_config(config, entry, repo_path, agent_type=AgentType.COPILOT)

        # Verify old file was removed
        assert not (github_dir / "old.md").exists(), "Old file should be removed"
        # Verify new structure was copied
        assert github_dir.exists(), ".github directory should exist after setup"
        assert (github_dir / AgentType.COPILOT.instruction_filename).exists(), "Main instruction file should exist"


def test_no_path_specific_instructions_warning():
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=DatasetEntry)
        entry.repo = "microsoftInternal/NAV"
        config = {"instructions": {"enabled": True}}

        # Setup instructions
        setup_instructions_from_config(config, entry, repo_path, agent_type=AgentType.COPILOT)

        # Verify repository-level instructions were created
        github_dir = repo_path / ".github"
        assert github_dir.exists(), ".github directory should be created"
        assert (github_dir / AgentType.COPILOT.instruction_filename).exists(), "Main instruction file should exist"


def test_empty_instructions_folder_warning():
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=DatasetEntry)
        entry.repo = "microsoftInternal/NAV"
        config = {"instructions": {"enabled": True}}

        # Setup instructions
        setup_instructions_from_config(config, entry, repo_path, agent_type=AgentType.COPILOT)

        # Verify .github directory was created
        github_dir = repo_path / ".github"
        assert github_dir.exists(), ".github directory should be created"
        assert (github_dir / AgentType.COPILOT.instruction_filename).exists(), "Main instruction file should exist"


def test_claude_instructions_renamed():
    instructions_source = _get_source_instructions_path("microsoftInternal/NAV")

    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=DatasetEntry)
        entry.repo = "microsoftInternal/NAV"
        config = {"instructions": {"enabled": True}}

        result = setup_instructions_from_config(config, entry, repo_path, agent_type=AgentType.CLAUDE)
        assert result is True

        claude_dir = repo_path / ".claude"
        assert claude_dir.exists(), ".claude directory should be created"

        # AGENTS.md should be renamed to CLAUDE.md
        assert not (claude_dir / _config.file_patterns.instruction_source_naming).exists(), "Source file should be renamed"
        claude_md = claude_dir / AgentType.CLAUDE.instruction_filename
        assert claude_md.exists(), "CLAUDE.md should exist"

        # Content should match the original source file
        source_content = (instructions_source / _config.file_patterns.instruction_source_naming).read_text(encoding="utf-8")
        assert claude_md.read_text(encoding="utf-8") == source_content, "CLAUDE.md content should match source"
