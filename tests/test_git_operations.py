"""Tests for git operations."""

import subprocess
import tempfile
from pathlib import Path

import pytest

from bcbench.exceptions import EmptyDiffError
from bcbench.operations.git_operations import clean_project_paths, get_generated_diff


class TestGetGeneratedDiff:
    """Test suite for get_generated_diff function."""

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
            (repo_path / "app" / "file.al").write_text("app content")
            (repo_path / "test" / "file.al").write_text("test content")

            # Commit initial state
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True, capture_output=True)

            yield repo_path

    def test_get_generated_diff_all_changes(self, temp_git_repo):
        """Test getting diff with all changes (no project_paths specified)."""
        # Make changes to both directories
        (temp_git_repo / "app" / "file.al").write_text("modified app content")
        (temp_git_repo / "test" / "file.al").write_text("modified test content")

        # Get diff without specifying project paths
        diff = get_generated_diff(temp_git_repo)

        # Verify both changes are in the diff
        assert "app/file.al" in diff
        assert "test/file.al" in diff
        assert "modified app content" in diff
        assert "modified test content" in diff

    def test_get_generated_diff_specific_project_only(self, temp_git_repo):
        """Test getting diff with only specific project changes."""
        # Make changes to both directories
        (temp_git_repo / "app" / "file.al").write_text("modified app content")
        (temp_git_repo / "test" / "file.al").write_text("modified test content")

        # Get diff for only app directory
        diff = get_generated_diff(temp_git_repo, ["app"])

        # Verify only app changes are in the diff
        assert "app/file.al" in diff
        assert "modified app content" in diff
        assert "test/file.al" not in diff
        assert "modified test content" not in diff

    def test_get_generated_diff_cleans_other_projects(self, temp_git_repo):
        """Test that changes in other projects are cleaned when project_paths is specified."""
        # Make changes to both directories
        (temp_git_repo / "app" / "file.al").write_text("modified app content")
        (temp_git_repo / "test" / "file.al").write_text("modified test content")
        (temp_git_repo / "test" / "new_file.al").write_text("new test content")

        # Get diff for only test directory
        get_generated_diff(temp_git_repo, ["test"])

        # Verify app changes are cleaned
        assert (temp_git_repo / "app" / "file.al").read_text() == "app content"
        # Verify test changes are preserved (staged)
        # Note: staged changes remain in working directory
        assert (temp_git_repo / "test" / "file.al").read_text() == "modified test content"

    def test_get_generated_diff_empty_raises_error(self, temp_git_repo):
        """Test that empty diff raises EmptyDiffError."""
        # Don't make any changes
        with pytest.raises(EmptyDiffError):
            get_generated_diff(temp_git_repo)

    def test_get_generated_diff_new_files(self, temp_git_repo):
        """Test that new files are included in the diff."""
        # Create new file
        (temp_git_repo / "app" / "new_file.al").write_text("new content")

        # Get diff for app directory
        diff = get_generated_diff(temp_git_repo, ["app"])

        # Verify new file is in the diff
        assert "app/new_file.al" in diff
        assert "new content" in diff


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
