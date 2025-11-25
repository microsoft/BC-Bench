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
        result = setup_instructions_from_config(config, entry, repo_path)
        assert result is True

        # Verify
        target_path = repo_path / ".github"
        assert target_path.exists(), ".github directory should be created"

        # Verify files were copied
        for item in instructions_source.iterdir():
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
        target_path = github_dir / _config.file_patterns.copilot_instruction_naming
        original_content = "# Original instructions\nThis should be overwritten"
        target_path.write_text(original_content)

        # Setup instructions (should overwrite)
        setup_instructions_from_config(config, entry, repo_path)

        # Verify file was overwritten
        assert target_path.exists(), "Instruction file should exist"
        new_content = target_path.read_text()
        assert new_content != original_content, "Content should be overwritten"
        source_file = instructions_source / _config.file_patterns.copilot_instruction_naming
        assert new_content == source_file.read_text(), "Content should match source"


def test_path_specific_instructions_copied():
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=DatasetEntry)
        entry.repo = "microsoftInternal/NAV"
        config = {"instructions": {"enabled": True}}

        # Setup instructions
        setup_instructions_from_config(config, entry, repo_path)

        # Verify path-specific instructions were copied
        target_instructions_dir = repo_path / ".github" / _config.file_patterns.copilot_instructions_dirname
        assert target_instructions_dir.exists(), "Instructions folder should be created"

        # Verify that at least some instruction files exist
        instruction_files = list(target_instructions_dir.glob(_config.file_patterns.copilot_instructions_pattern))
        assert len(instruction_files) > 0, "At least one instruction file should be copied"


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
        setup_instructions_from_config(config, entry, repo_path)

        # Verify old file was removed
        assert not (github_dir / "old.md").exists(), "Old file should be removed"
        # Verify new structure was copied
        assert github_dir.exists(), ".github directory should exist after setup"
        assert (github_dir / _config.file_patterns.copilot_instruction_naming).exists(), "Main instruction file should exist"


def test_no_path_specific_instructions_warning():
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=DatasetEntry)
        entry.repo = "microsoftInternal/NAV"
        config = {"instructions": {"enabled": True}}

        # Setup instructions
        setup_instructions_from_config(config, entry, repo_path)

        # Verify repository-level instructions were created
        github_dir = repo_path / ".github"
        assert github_dir.exists(), ".github directory should be created"
        assert (github_dir / _config.file_patterns.copilot_instruction_naming).exists(), "Main instruction file should exist"


def test_empty_instructions_folder_warning():
    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        entry = MagicMock(spec=DatasetEntry)
        entry.repo = "microsoftInternal/NAV"
        config = {"instructions": {"enabled": True}}

        # Setup instructions
        setup_instructions_from_config(config, entry, repo_path)

        # Verify .github directory was created
        github_dir = repo_path / ".github"
        assert github_dir.exists(), ".github directory should be created"
        assert (github_dir / _config.file_patterns.copilot_instruction_naming).exists(), "Main instruction file should exist"
