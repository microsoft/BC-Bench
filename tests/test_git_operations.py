import subprocess
import tempfile
from pathlib import Path

import pytest

from bcbench.exceptions import EmptyDiffError
from bcbench.operations.git_operations import stage_and_get_diff


class TestStageAndGetDiff:
    @pytest.fixture
    def temp_git_repo(self):
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
        # Make changes to both directories
        (temp_git_repo / "app" / "file.al").write_text("modified app content")
        (temp_git_repo / "test" / "file.al").write_text("modified test content")

        # Get diff - stages all *.al files
        diff = stage_and_get_diff(temp_git_repo)

        # Verify both changes are in the diff
        assert "app/file.al" in diff
        assert "test/file.al" in diff
        assert "modified app content" in diff
        assert "modified test content" in diff

    def test_stage_and_get_diff_empty_raises_error(self, temp_git_repo):
        """Test that empty diff raises EmptyDiffError."""
        # Don't make any changes
        with pytest.raises(EmptyDiffError):
            stage_and_get_diff(temp_git_repo)
