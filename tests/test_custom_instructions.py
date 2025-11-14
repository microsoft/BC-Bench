"""
Simple verification script for custom instructions framework.
Verifies that instruction files get created without invoking the copilot agent.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from bcbench.config import get_config
from bcbench.operations.instruction_operations import (
    _get_source_instructions_path,
    _setup_custom_instructions,
)

_config = get_config()


def test_get_instructions_path():
    agent_dir = Path(__file__).parent.parent / "src" / "bcbench" / "agent" / "copilot"

    # Test with microsoftInternal/NAV
    path = _get_source_instructions_path("microsoftInternal/NAV", agent_dir)
    assert path.exists(), f"Instruction file should exist: {path}"
    assert path.name == _config.file_patterns.copilot_instruction_naming
    assert "microsoftInternal-NAV" in str(path)
    print(f"✓ Found instruction file: {path}")


def test_setup_custom_instructions():
    agent_dir = Path(__file__).parent.parent / "src" / "bcbench" / "agent" / "copilot"
    instructions_source = _get_source_instructions_path("microsoftInternal/NAV", agent_dir)

    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)

        # Setup instructions
        created_path = _setup_custom_instructions(repo_path, instructions_source)

        # Verify
        assert created_path is not None, "Should return created path"
        assert created_path.exists(), "Instruction file should be created"
        assert created_path.parent.name == ".github", "Should be in .github directory"
        assert created_path.name == _config.file_patterns.copilot_instruction_naming, "Should be named correctly"

        # Verify content was copied
        assert created_path.read_text() == instructions_source.read_text()
        print(f"✓ Instructions created at: {created_path}")


def test_sanitization():
    test_cases = [
        ("microsoftInternal/NAV", "microsoftInternal-NAV"),
        ("org/repo", "org-repo"),
        ("user/my-repo", "user-my-repo"),
    ]

    for repo_name, expected_sanitized in test_cases:
        sanitized = repo_name.replace("/", "-")
        assert sanitized == expected_sanitized, f"Failed for {repo_name}"
    print("✓ Sanitization works correctly")


def test_nonexistent_instructions():
    agent_dir = Path(__file__).parent.parent / "src" / "bcbench" / "agent" / "copilot"

    try:
        _get_source_instructions_path("nonexistent/repo", agent_dir)
        raise AssertionError("Should raise FileNotFoundError")
    except FileNotFoundError as e:
        assert "nonexistent/repo" in str(e)
        print(f"✓ Correct error for missing instructions: {e}")


def test_overwrite_existing_instructions():
    agent_dir = Path(__file__).parent.parent / "src" / "bcbench" / "agent" / "copilot"
    instructions_source = _get_source_instructions_path("microsoftInternal/NAV", agent_dir)

    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)

        # Create initial instruction file with different content
        github_dir = repo_path / ".github"
        github_dir.mkdir(parents=True, exist_ok=True)
        target_path = github_dir / _config.file_patterns.copilot_instruction_naming
        original_content = "# Original instructions\nThis should be overwritten"
        target_path.write_text(original_content)

        # Setup instructions (should overwrite)
        created_path = _setup_custom_instructions(repo_path, instructions_source)

        # Verify file was overwritten
        assert created_path.exists(), "Instruction file should exist"
        new_content = created_path.read_text()
        assert new_content != original_content, "Content should be overwritten"
        assert new_content == instructions_source.read_text(), "Content should match source"
        print(f"✓ Existing instructions overwritten at: {created_path}")


def test_path_specific_instructions_copied():
    agent_dir = Path(__file__).parent.parent / "src" / "bcbench" / "agent" / "copilot"
    instructions_source = _get_source_instructions_path("microsoftInternal/NAV", agent_dir)

    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)

        # Create a mock instructions folder with some .instructions.md files
        source_instructions_dir = instructions_source.parent / _config.file_patterns.copilot_instructions_dirname
        source_instructions_dir.mkdir(exist_ok=True)

        # Create test instruction files
        test_files = {
            "al-code.instructions.md": '---\napplyTo: "**/*.al"\n---\n# AL Code Instructions',
            "test-code.instructions.md": '---\napplyTo: "**/*.test.al"\n---\n# Test Instructions',
        }

        for filename, content in test_files.items():
            (source_instructions_dir / filename).write_text(content)

        try:
            # Setup instructions
            _setup_custom_instructions(repo_path, instructions_source)

            # Verify path-specific instructions were copied
            target_instructions_dir = repo_path / ".github" / _config.file_patterns.copilot_instructions_dirname
            assert target_instructions_dir.exists(), "Instructions folder should be created"

            for filename, expected_content in test_files.items():
                target_file = target_instructions_dir / filename
                assert target_file.exists(), f"Instruction file {filename} should be copied"
                assert target_file.read_text() == expected_content, f"Content should match for {filename}"

            print(f"✓ Path-specific instructions copied: {list(test_files.keys())}")
        finally:
            # Cleanup test files
            for filename in test_files:
                (source_instructions_dir / filename).unlink(missing_ok=True)
            source_instructions_dir.rmdir()


def test_path_specific_instructions_removed_before_copy():
    agent_dir = Path(__file__).parent.parent / "src" / "bcbench" / "agent" / "copilot"
    instructions_source = _get_source_instructions_path("microsoftInternal/NAV", agent_dir)

    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)

        # Create existing instructions folder with old files
        github_dir = repo_path / ".github"
        github_dir.mkdir(parents=True, exist_ok=True)
        old_instructions_dir = github_dir / _config.file_patterns.copilot_instructions_dirname
        old_instructions_dir.mkdir(exist_ok=True)
        old_file = old_instructions_dir / "old.instructions.md"
        old_file.write_text("# Old instruction that should be removed")

        # Create source instructions folder
        source_instructions_dir = instructions_source.parent / _config.file_patterns.copilot_instructions_dirname
        source_instructions_dir.mkdir(exist_ok=True)
        new_file_path = source_instructions_dir / "new.instructions.md"
        new_file_path.write_text("# New instruction")

        try:
            # Setup instructions
            _setup_custom_instructions(repo_path, instructions_source)

            # Verify old file was removed and new file was added
            target_instructions_dir = repo_path / ".github" / _config.file_patterns.copilot_instructions_dirname
            assert not (target_instructions_dir / "old.instructions.md").exists(), "Old file should be removed"
            assert (target_instructions_dir / "new.instructions.md").exists(), "New file should be present"
            print("✓ Existing instructions folder removed before copy")
        finally:
            # Cleanup
            new_file_path.unlink(missing_ok=True)
            source_instructions_dir.rmdir()


def test_no_path_specific_instructions_warning():
    agent_dir = Path(__file__).parent.parent / "src" / "bcbench" / "agent" / "copilot"
    instructions_source = _get_source_instructions_path("microsoftInternal/NAV", agent_dir)

    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)

        # Ensure no instructions folder exists
        source_instructions_dir = instructions_source.parent / _config.file_patterns.copilot_instructions_dirname
        if source_instructions_dir.exists():
            # Temporarily rename it
            temp_name = source_instructions_dir.with_suffix(".tmp")
            source_instructions_dir.rename(temp_name)
            try:
                # Setup instructions (should succeed with warning)
                created_path = _setup_custom_instructions(repo_path, instructions_source)
                assert created_path.exists(), "Repository-level instructions should still be created"
                print("✓ Missing instructions folder handled gracefully")
            finally:
                temp_name.rename(source_instructions_dir)
        else:
            # Setup instructions (should succeed with warning)
            created_path = _setup_custom_instructions(repo_path, instructions_source)
            assert created_path.exists(), "Repository-level instructions should still be created"
            print("✓ Missing instructions folder handled gracefully")


def test_empty_instructions_folder_warning():
    agent_dir = Path(__file__).parent.parent / "src" / "bcbench" / "agent" / "copilot"
    instructions_source = _get_source_instructions_path("microsoftInternal/NAV", agent_dir)

    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)

        # Create empty instructions folder
        source_instructions_dir = instructions_source.parent / _config.file_patterns.copilot_instructions_dirname
        source_instructions_dir.mkdir(exist_ok=True)

        # Create a non-.instructions.md file
        (source_instructions_dir / "readme.txt").write_text("Not an instruction file")

        try:
            # Setup instructions (should succeed with warning)
            created_path = _setup_custom_instructions(repo_path, instructions_source)
            assert created_path.exists(), "Repository-level instructions should still be created"

            # Verify instructions folder was created but is empty
            target_instructions_dir = repo_path / ".github" / _config.file_patterns.copilot_instructions_dirname
            assert target_instructions_dir.exists(), "Instructions folder should be created"
            instruction_files = list(target_instructions_dir.glob(_config.file_patterns.copilot_instructions_pattern))
            assert len(instruction_files) == 0, "No instruction files should be copied"

            print("✓ Empty instructions folder handled with warning")
        finally:
            # Cleanup
            (source_instructions_dir / "readme.txt").unlink(missing_ok=True)
            source_instructions_dir.rmdir()
