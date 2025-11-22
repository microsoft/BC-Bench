"""Tests for git operations."""

import subprocess
import tempfile
from pathlib import Path

import pytest

from bcbench.exceptions import EmptyDiffError
from bcbench.operations.git_operations import stage_and_get_diff


class TestStageAndGetDiff:
    """Test suite for stage_and_get_diff function."""

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

    def test_stage_and_get_diff_all_changes(self, temp_git_repo):
        """Test getting diff with all changes (no project_paths specified)."""
        # Make changes to both directories
        (temp_git_repo / "app" / "file.al").write_text("modified app content")
        (temp_git_repo / "test" / "file.al").write_text("modified test content")

        # Get diff without specifying project paths
        diff = stage_and_get_diff(temp_git_repo)

        # Verify both changes are in the diff
        assert "app/file.al" in diff
        assert "test/file.al" in diff
        assert "modified app content" in diff
        assert "modified test content" in diff

    def test_stage_and_get_diff_specific_project_only(self, temp_git_repo):
        """Test getting diff with only specific project changes."""
        # Make changes to both directories
        (temp_git_repo / "app" / "file.al").write_text("modified app content")
        (temp_git_repo / "test" / "file.al").write_text("modified test content")

        # Get diff for only app directory
        diff = stage_and_get_diff(temp_git_repo, ["app"])

        # Verify only app changes are in the diff
        assert "app/file.al" in diff
        assert "modified app content" in diff
        assert "test/file.al" not in diff
        assert "modified test content" not in diff

    def test_stage_and_get_diff_cleans_other_projects(self, temp_git_repo):
        """Test that changes in other projects are cleaned when project_paths is specified."""
        # Make changes to both directories
        (temp_git_repo / "app" / "file.al").write_text("modified app content")
        (temp_git_repo / "test" / "file.al").write_text("modified test content")
        (temp_git_repo / "test" / "new_file.al").write_text("new test content")

        # Get diff for only test directory
        stage_and_get_diff(temp_git_repo, ["test"])

        # Verify app changes are cleaned
        assert (temp_git_repo / "app" / "file.al").read_text() == "app content"
        # Verify test changes are preserved (staged)
        # Note: staged changes remain in working directory
        assert (temp_git_repo / "test" / "file.al").read_text() == "modified test content"

    def test_stage_and_get_diff_empty_raises_error(self, temp_git_repo):
        """Test that empty diff raises EmptyDiffError."""
        # Don't make any changes
        with pytest.raises(EmptyDiffError):
            stage_and_get_diff(temp_git_repo)

    def test_stage_and_get_diff_new_files(self, temp_git_repo):
        """Test that new files are included in the diff."""
        # Create new file
        (temp_git_repo / "app" / "new_file.al").write_text("new content")

        # Get diff for app directory
        diff = stage_and_get_diff(temp_git_repo, ["app"])

        # Verify new file is in the diff
        assert "app/new_file.al" in diff
        assert "new content" in diff

    def test_stage_and_get_diff_handles_pre_staged_files(self, temp_git_repo):
        """Test that pre-staged files are unstaged before operation."""
        # Make changes and stage them
        (temp_git_repo / "app" / "file.al").write_text("pre-staged content")
        subprocess.run(["git", "add", "app/file.al"], cwd=temp_git_repo, check=True, capture_output=True)

        # Make additional changes
        (temp_git_repo / "test" / "file.al").write_text("modified test content")

        # Get diff for only test directory
        diff = stage_and_get_diff(temp_git_repo, ["test"])

        # Verify only test changes are in the diff (pre-staged app changes were unstaged and cleaned)
        assert "test/file.al" in diff
        assert "app/file.al" not in diff
        assert "pre-staged content" not in diff

    def test_stage_and_get_diff_multiple_project_paths(self, temp_git_repo):
        """Test staging multiple project paths."""
        # Make changes to both directories
        (temp_git_repo / "app" / "file.al").write_text("modified app content")
        (temp_git_repo / "test" / "file.al").write_text("modified test content")

        # Get diff for both directories
        diff = stage_and_get_diff(temp_git_repo, ["app", "test"])

        # Verify both changes are in the diff
        assert "app/file.al" in diff
        assert "test/file.al" in diff

    def test_stage_and_get_diff_with_subdirectories(self, temp_git_repo):
        """Test that subdirectories are handled correctly."""
        # Create subdirectory with file
        (temp_git_repo / "app" / "subdir").mkdir()
        (temp_git_repo / "app" / "subdir" / "nested.al").write_text("nested content")

        # Get diff for app directory
        diff = stage_and_get_diff(temp_git_repo, ["app"])

        # Verify nested file is in the diff
        assert "app/subdir/nested.al" in diff
        assert "nested content" in diff

    def test_stage_and_get_diff_excludes_non_al_files(self, temp_git_repo):
        """Test that non-.al files are excluded from diff."""
        # Create various file types
        (temp_git_repo / "app" / "file.al").write_text("al content")
        (temp_git_repo / "app" / "readme.md").write_text("readme content")
        (temp_git_repo / "app" / "app.json").write_text('{"name": "test"}')

        # Get diff
        diff = stage_and_get_diff(temp_git_repo, ["app"])

        # Verify only .al file is in diff
        assert "file.al" in diff
        assert "readme.md" not in diff
        assert "app.json" not in diff
