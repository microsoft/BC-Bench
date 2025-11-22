"""Tests for git operations."""

import subprocess
import tempfile
from pathlib import Path

import pytest

from bcbench.operations.git_operations import clean_project_paths


class TestCleanProjectPaths:
    """Test suite for clean_project_paths function."""

    @pytest.fixture
    def temp_git_repo(self):
        """Create a temporary git repository for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Initialize git repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)

            # Create initial structure
            (repo_path / "app").mkdir()
            (repo_path / "test").mkdir()
            (repo_path / "app" / "file.txt").write_text("app content")
            (repo_path / "test" / "file.txt").write_text("test content")

            # Commit initial state
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True, capture_output=True)

            yield repo_path

    def test_clean_single_project_path(self, temp_git_repo):
        """Test cleaning a single project path."""
        # Make changes to test directory
        (temp_git_repo / "test" / "file.txt").write_text("modified test content")
        (temp_git_repo / "test" / "new_file.txt").write_text("new content")

        # Clean test directory
        clean_project_paths(temp_git_repo, ["test"])

        # Verify test directory is cleaned
        assert (temp_git_repo / "test" / "file.txt").read_text() == "test content"
        assert not (temp_git_repo / "test" / "new_file.txt").exists()

        # Verify app directory is unchanged
        assert (temp_git_repo / "app" / "file.txt").read_text() == "app content"

    def test_clean_multiple_project_paths(self, temp_git_repo):
        """Test cleaning multiple project paths."""
        # Make changes to both directories
        (temp_git_repo / "app" / "file.txt").write_text("modified app content")
        (temp_git_repo / "test" / "file.txt").write_text("modified test content")

        # Clean both directories
        clean_project_paths(temp_git_repo, ["app", "test"])

        # Verify both directories are cleaned
        assert (temp_git_repo / "app" / "file.txt").read_text() == "app content"
        assert (temp_git_repo / "test" / "file.txt").read_text() == "test content"

    def test_clean_with_empty_list(self, temp_git_repo):
        """Test that cleaning with empty list does nothing."""
        # Make changes
        (temp_git_repo / "app" / "file.txt").write_text("modified app content")

        # Clean with empty list
        clean_project_paths(temp_git_repo, [])

        # Verify changes are still there
        assert (temp_git_repo / "app" / "file.txt").read_text() == "modified app content"

    def test_clean_removes_untracked_files(self, temp_git_repo):
        """Test that untracked files are removed."""
        # Create untracked files
        (temp_git_repo / "test" / "untracked1.txt").write_text("untracked")
        (temp_git_repo / "test" / "subdir").mkdir()
        (temp_git_repo / "test" / "subdir" / "untracked2.txt").write_text("untracked")

        # Clean test directory
        clean_project_paths(temp_git_repo, ["test"])

        # Verify untracked files are removed
        assert not (temp_git_repo / "test" / "untracked1.txt").exists()
        assert not (temp_git_repo / "test" / "subdir").exists()

    def test_clean_preserves_staged_changes_in_other_paths(self, temp_git_repo):
        """Test that staged changes in other paths are preserved."""
        # Make and stage changes in app directory
        (temp_git_repo / "app" / "file.txt").write_text("staged changes")
        subprocess.run(["git", "add", "app/file.txt"], cwd=temp_git_repo, check=True, capture_output=True)

        # Make changes in test directory
        (temp_git_repo / "test" / "file.txt").write_text("modified test content")

        # Clean test directory
        clean_project_paths(temp_git_repo, ["test"])

        # Verify test directory is cleaned
        assert (temp_git_repo / "test" / "file.txt").read_text() == "test content"

        # Verify app directory still has staged changes
        assert (temp_git_repo / "app" / "file.txt").read_text() == "staged changes"
