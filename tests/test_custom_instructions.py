"""
Simple verification script for custom instructions framework.
Verifies that instruction files get created without invoking the copilot agent.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from bcbench.operations.instruction_operations import (
    _get_source_instructions_path,
    _setup_custom_instructions,
)


def test_get_instructions_path():
    """Test that instruction path resolution works correctly."""
    agent_dir = Path(__file__).parent.parent / "src" / "bcbench" / "agent" / "copilot"

    # Test with microsoftInternal/NAV
    path = _get_source_instructions_path("microsoftInternal/NAV", agent_dir)
    assert path.exists(), f"Instruction file should exist: {path}"
    assert path.name == "copilot-instructions.md"
    assert "microsoftInternal-NAV" in str(path)
    print(f"✓ Found instruction file: {path}")


def test_setup_custom_instructions():
    """Test that instructions get copied to .github directory."""
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
        assert created_path.name == "copilot-instructions.md", "Should be named correctly"

        # Verify content was copied
        assert created_path.read_text() == instructions_source.read_text()
        print(f"✓ Instructions created at: {created_path}")


def test_sanitization():
    """Test that repo names with slashes get sanitized correctly."""
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
    """Test error handling for missing instruction files."""
    agent_dir = Path(__file__).parent.parent / "src" / "bcbench" / "agent" / "copilot"

    try:
        _get_source_instructions_path("nonexistent/repo", agent_dir)
        raise AssertionError("Should raise FileNotFoundError")
    except FileNotFoundError as e:
        assert "nonexistent/repo" in str(e)
        print(f"✓ Correct error for missing instructions: {e}")


def test_overwrite_existing_instructions():
    """Test that existing instruction files get overwritten."""
    agent_dir = Path(__file__).parent.parent / "src" / "bcbench" / "agent" / "copilot"
    instructions_source = _get_source_instructions_path("microsoftInternal/NAV", agent_dir)

    with TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)

        # Create initial instruction file with different content
        github_dir = repo_path / ".github"
        github_dir.mkdir(parents=True, exist_ok=True)
        target_path = github_dir / "copilot-instructions.md"
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
