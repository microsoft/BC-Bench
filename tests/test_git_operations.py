import subprocess
import tempfile
from pathlib import Path

import pytest

from bcbench.exceptions import EmptyDiffError
from bcbench.operations.git_operations import clean_project_paths, commit_changes, stage_and_get_diff


class TestCommitChanges:
    @pytest.fixture
    def temp_git_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)
            (repo_path / "file.al").write_text("original")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo_path, check=True, capture_output=True)
            yield repo_path

    def test_committed_changes_excluded_from_diff(self, temp_git_repo):
        (temp_git_repo / "file.al").write_text("setup change")
        commit_changes(temp_git_repo, "setup")

        (temp_git_repo / "file.al").write_text("agent change")
        diff = stage_and_get_diff(temp_git_repo)

        assert "agent change" in diff
        # The diff should be against the committed "setup change", not the original "original"
        assert "-original" not in diff
        assert "-setup change" in diff

    def test_commit_works_without_global_git_identity(self, temp_git_repo):
        # Unset local user config to simulate CI environment
        subprocess.run(["git", "config", "--unset", "user.email"], cwd=temp_git_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "--unset", "user.name"], cwd=temp_git_repo, check=True, capture_output=True)

        (temp_git_repo / "file.al").write_text("changed")
        commit_changes(temp_git_repo, "should work without identity")

        result = subprocess.run(["git", "log", "--oneline", "-1"], cwd=temp_git_repo, capture_output=True, text=True, check=True)
        assert "should work without identity" in result.stdout


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
        # Don't make any changes
        with pytest.raises(EmptyDiffError):
            stage_and_get_diff(temp_git_repo)


class TestCleanProjectPaths:
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

    def test_clean_project_paths_reverts_modified_files(self, temp_git_repo):
        # Modify files in test directory
        (temp_git_repo / "test" / "file.al").write_text("modified test content")

        # Clean test directory
        clean_project_paths(temp_git_repo, ["test"])

        # Verify file is reverted to original content
        assert (temp_git_repo / "test" / "file.al").read_text() == "test content"

    def test_clean_project_paths_removes_untracked_files(self, temp_git_repo):
        # Create new file in test directory
        (temp_git_repo / "test" / "new_file.al").write_text("new content")

        # Clean test directory
        clean_project_paths(temp_git_repo, ["test"])

        # Verify new file is removed
        assert not (temp_git_repo / "test" / "new_file.al").exists()

    def test_clean_project_paths_unstages_staged_changes(self, temp_git_repo):
        # Modify and stage file
        (temp_git_repo / "test" / "file.al").write_text("staged content")
        subprocess.run(["git", "add", "test/file.al"], cwd=temp_git_repo, check=True, capture_output=True)

        # Clean test directory
        clean_project_paths(temp_git_repo, ["test"])

        # Verify file is reverted and not staged
        assert (temp_git_repo / "test" / "file.al").read_text() == "test content"
        result = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=temp_git_repo, capture_output=True, text=True, check=True)
        assert "test/file.al" not in result.stdout

    def test_clean_project_paths_preserves_other_projects(self, temp_git_repo):
        # Make changes to both directories
        (temp_git_repo / "app" / "file.al").write_text("modified app content")
        (temp_git_repo / "test" / "file.al").write_text("modified test content")

        # Clean only test directory
        clean_project_paths(temp_git_repo, ["test"])

        # Verify app changes are preserved
        assert (temp_git_repo / "app" / "file.al").read_text() == "modified app content"
        # Verify test changes are reverted
        assert (temp_git_repo / "test" / "file.al").read_text() == "test content"

    def test_clean_project_paths_multiple_projects(self, temp_git_repo):
        # Create third directory
        (temp_git_repo / "lib").mkdir()
        (temp_git_repo / "lib" / "file.al").write_text("lib content")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add lib"], cwd=temp_git_repo, check=True, capture_output=True)

        # Modify all directories
        (temp_git_repo / "app" / "file.al").write_text("modified app")
        (temp_git_repo / "test" / "file.al").write_text("modified test")
        (temp_git_repo / "lib" / "file.al").write_text("modified lib")

        # Clean test and lib directories
        clean_project_paths(temp_git_repo, ["test", "lib"])

        # Verify app changes preserved, others reverted
        assert (temp_git_repo / "app" / "file.al").read_text() == "modified app"
        assert (temp_git_repo / "test" / "file.al").read_text() == "test content"
        assert (temp_git_repo / "lib" / "file.al").read_text() == "lib content"

    def test_clean_project_paths_with_subdirectories(self, temp_git_repo):
        # Create subdirectory with file
        (temp_git_repo / "test" / "subdir").mkdir()
        (temp_git_repo / "test" / "subdir" / "nested.al").write_text("nested content")
        subprocess.run(["git", "add", "."], cwd=temp_git_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add nested file"], cwd=temp_git_repo, check=True, capture_output=True)

        # Modify nested file and create new one
        (temp_git_repo / "test" / "subdir" / "nested.al").write_text("modified nested")
        (temp_git_repo / "test" / "subdir" / "new.al").write_text("new nested")

        # Clean test directory
        clean_project_paths(temp_git_repo, ["test"])

        # Verify nested file reverted and new file removed
        assert (temp_git_repo / "test" / "subdir" / "nested.al").read_text() == "nested content"
        assert not (temp_git_repo / "test" / "subdir" / "new.al").exists()

    def test_clean_project_paths_empty_list_raises_error(self, temp_git_repo):
        with pytest.raises(ValueError, match="No project paths provided"):
            clean_project_paths(temp_git_repo, [])
