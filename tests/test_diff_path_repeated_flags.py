from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from bcbench.cli import app
from bcbench.collection.patch_utils import extract_patches
from bcbench.exceptions import CollectionError

runner = CliRunner()


class TestExtractPatchesWithMultipleDiffPaths:
    def test_single_diff_path(self, tmp_path):
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
        repo_path = tmp_path / "nonexistent"

        with pytest.raises(FileNotFoundError, match="Repository not found"):
            extract_patches(
                repo_path,
                "base123",
                "commit456",
                diff_path=["some/path"],
            )

    def test_git_command_with_special_characters_in_path(self, tmp_path):
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


class TestCLIRepeatedFlags:
    @pytest.mark.integration
    def test_cli_accepts_multiple_diff_path_flags(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with patch("bcbench.commands.collect.collect_nav_entry") as mock_collect:
            result = runner.invoke(
                app,
                [
                    "collect",
                    "nav",
                    "12345",
                    "--repo-path",
                    str(repo_path),
                    "--diff-path",
                    "App/Layers/W1/BaseApp",
                    "--diff-path",
                    "App/Apps/W1/Shopify",
                ],
            )

            assert result.exit_code == 0, f"CLI failed: {result.output}"
            mock_collect.assert_called_once()
            call_kwargs = mock_collect.call_args[1]
            assert call_kwargs["diff_path"] == ["App/Layers/W1/BaseApp", "App/Apps/W1/Shopify"]

    @pytest.mark.integration
    def test_cli_accepts_single_diff_path_flag(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with patch("bcbench.commands.collect.collect_nav_entry") as mock_collect:
            result = runner.invoke(
                app,
                [
                    "collect",
                    "nav",
                    "12345",
                    "--repo-path",
                    str(repo_path),
                    "--diff-path",
                    "App/Layers/W1/BaseApp",
                ],
            )

            assert result.exit_code == 0, f"CLI failed: {result.output}"
            mock_collect.assert_called_once()
            call_kwargs = mock_collect.call_args[1]
            assert call_kwargs["diff_path"] == ["App/Layers/W1/BaseApp"]

    @pytest.mark.integration
    def test_cli_works_without_diff_path_flag(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with patch("bcbench.commands.collect.collect_nav_entry") as mock_collect:
            result = runner.invoke(
                app,
                [
                    "collect",
                    "nav",
                    "12345",
                    "--repo-path",
                    str(repo_path),
                ],
            )

            assert result.exit_code == 0, f"CLI failed: {result.output}"
            mock_collect.assert_called_once()
            call_kwargs = mock_collect.call_args[1]
            assert call_kwargs["diff_path"] is None
