"""Tests for repeated diff_path flags functionality."""

from unittest.mock import MagicMock, patch

import pytest

from bcbench.collection.patch_utils import extract_patches
from bcbench.exceptions import CollectionError


class TestExtractPatchesWithMultipleDiffPaths:
    """Test extract_patches function with repeated diff_path flags."""

    def test_single_diff_path(self, tmp_path):
        """Test with a single diff_path (backward compatibility)."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="diff --git a/App/Layers/W1/BaseApp/file.al b/App/Layers/W1/BaseApp/file.al\n+fix",
            )

            _full, fix, _test = extract_patches(
                repo_path,
                "base123",
                "commit456",
                diff_path=["App/Layers/W1/BaseApp"],
            )

            # Verify git command was called with correct arguments
            call_args = mock_run.call_args[0][0]
            assert call_args == ["git", "diff", "base123", "commit456", "--", "App/Layers/W1/BaseApp"]
            assert "fix" in fix

    def test_multiple_diff_paths(self, tmp_path):
        """Test with multiple diff_path values."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="diff --git a/App/Layers/W1/BaseApp/file.al b/App/Layers/W1/BaseApp/file.al\n+fix\ndiff --git a/App/Apps/W1/Shopify/app/file.al b/App/Apps/W1/Shopify/app/file.al\n+another fix",
            )

            _full, fix, _test = extract_patches(
                repo_path,
                "base123",
                "commit456",
                diff_path=["App/Layers/W1/BaseApp", "App/Apps/W1/Shopify"],
            )

            # Verify git command was called with both paths
            call_args = mock_run.call_args[0][0]
            assert call_args == [
                "git",
                "diff",
                "base123",
                "commit456",
                "--",
                "App/Layers/W1/BaseApp",
                "App/Apps/W1/Shopify",
            ]
            assert "fix" in fix
            assert "another fix" in fix

    def test_empty_diff_path_list(self, tmp_path):
        """Test with empty diff_path list (no filtering)."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="diff --git a/src/app/file.al b/src/app/file.al\n--- a/src/app/file.al\n+++ b/src/app/file.al\n@@ -1,3 +1,4 @@\n+all changes\n procedure Main()\n begin\n end;",
            )

            _full, fix, _test = extract_patches(
                repo_path,
                "base123",
                "commit456",
                diff_path=[],
            )

            # Verify git command was called without any path filter
            call_args = mock_run.call_args[0][0]
            assert call_args == ["git", "diff", "base123", "commit456"]
            assert "all changes" in fix

    def test_none_diff_path(self, tmp_path):
        """Test with None diff_path (default behavior)."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="diff --git a/src/app/file.al b/src/app/file.al\n--- a/src/app/file.al\n+++ b/src/app/file.al\n@@ -1,3 +1,4 @@\n+all changes\n procedure Main()\n begin\n end;",
            )

            _full, fix, _test = extract_patches(
                repo_path,
                "base123",
                "commit456",
                diff_path=None,
            )

            # Verify git command was called without any path filter
            call_args = mock_run.call_args[0][0]
            assert call_args == ["git", "diff", "base123", "commit456"]
            assert "all changes" in fix

    def test_diff_path_separates_test_and_fix_patches(self, tmp_path):
        """Test that diff_path filtering still properly separates test and fix patches."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        diff_output = """diff --git a/App/Layers/W1/BaseApp/Sales.Codeunit.al b/App/Layers/W1/BaseApp/Sales.Codeunit.al
--- a/App/Layers/W1/BaseApp/Sales.Codeunit.al
+++ b/App/Layers/W1/BaseApp/Sales.Codeunit.al
@@ -1,3 +1,4 @@
+// Fix code
 procedure MainCode()
 begin
 end;
diff --git a/App/Layers/W1/Tests/ERM/SalesTest.Codeunit.al b/App/Layers/W1/Tests/ERM/SalesTest.Codeunit.al
--- a/App/Layers/W1/Tests/ERM/SalesTest.Codeunit.al
+++ b/App/Layers/W1/Tests/ERM/SalesTest.Codeunit.al
@@ -1,3 +1,4 @@
+// Test code
 procedure TestCode()
 begin
 end;
"""

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=diff_output,
            )

            full, fix, test = extract_patches(
                repo_path,
                "base123",
                "commit456",
                diff_path=["App/Layers/W1"],
            )

            # Verify git command includes the path filter
            call_args = mock_run.call_args[0][0]
            assert "App/Layers/W1" in call_args

            # Verify separation of test and fix patches
            assert "Fix code" in fix
            assert "Test code" not in fix
            assert "Test code" in test
            assert "Fix code" not in test
            assert "Fix code" in full
            assert "Test code" in full

    def test_raises_error_when_no_patch_found(self, tmp_path):
        """Test that CollectionError is raised when no patch data is found."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="",
            )

            with pytest.raises(CollectionError, match="No patch data found"):
                extract_patches(
                    repo_path,
                    "base123",
                    "commit456",
                    diff_path=["App/Layers/W1/BaseApp"],
                )

    def test_raises_error_when_repo_not_found(self, tmp_path):
        """Test that FileNotFoundError is raised when repository doesn't exist."""
        repo_path = tmp_path / "nonexistent"

        with pytest.raises(FileNotFoundError, match="Repository not found"):
            extract_patches(
                repo_path,
                "base123",
                "commit456",
                diff_path=["some/path"],
            )

    def test_git_command_with_special_characters_in_path(self, tmp_path):
        """Test that paths with special characters are handled correctly."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="diff --git a/test.al b/test.al\n+changes",
            )

            extract_patches(
                repo_path,
                "base123",
                "commit456",
                diff_path=["App\\Layers\\W1\\BaseApp", "App/Apps/W1/Test Project"],
            )

            # Verify paths are passed as-is to git
            call_args = mock_run.call_args[0][0]
            assert "App\\Layers\\W1\\BaseApp" in call_args
            assert "App/Apps/W1/Test Project" in call_args
