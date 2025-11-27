"""Tests for the bcbench collect gh command."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from bcbench.collection.gh_client import GHClient
from bcbench.collection.patch_utils import find_project_paths_from_diff, separate_patches
from bcbench.exceptions import CollectionError
from bcbench.operations.test_operations import extract_codeunit_id_from_content


class TestExtractCodeunitIdFromContent:
    def test_extracts_codeunit_id_from_al_content(self):
        content = """codeunit 12345 "Test Codeunit"
{
    [Test]
    procedure TestFunction()
    begin
    end;
}"""
        result = extract_codeunit_id_from_content(content, "test.al")
        assert result == 12345

    def test_extracts_codeunit_id_with_spaces(self):
        content = 'codeunit  139500  "My Test Codeunit"'
        result = extract_codeunit_id_from_content(content, "test.al")
        assert result == 139500

    def test_raises_value_error_when_no_codeunit_found(self):
        content = "procedure TestFunction() begin end;"
        with pytest.raises(ValueError, match="No codeunit ID found"):
            extract_codeunit_id_from_content(content, "test.al")


class TestSeparatePatches:
    def test_separates_test_and_fix_patches(self):
        diff = """diff --git a/src/app/Code.al b/src/app/Code.al
--- a/src/app/Code.al
+++ b/src/app/Code.al
@@ -1,3 +1,4 @@
+// Fix code
 procedure MainCode()
 begin
 end;
diff --git a/src/test/Test.al b/src/test/Test.al
--- a/src/test/Test.al
+++ b/src/test/Test.al
@@ -1,3 +1,4 @@
+// Test code
 procedure TestCode()
 begin
 end;
"""
        test_identifiers = ("test",)
        full, fix, test = separate_patches(diff, test_identifiers)

        assert "Fix code" in fix
        assert "Test code" in test
        assert "Fix code" in full
        assert "Test code" in full

    def test_raises_collection_error_on_empty_diff(self):
        with pytest.raises(CollectionError, match="No diff data found"):
            separate_patches("", ("test",))

    def test_handles_diff_with_no_test_files(self):
        diff = """diff --git a/src/app/Code.al b/src/app/Code.al
--- a/src/app/Code.al
+++ b/src/app/Code.al
@@ -1,3 +1,4 @@
+// Fix code
 procedure MainCode()
 begin
 end;
"""
        _full, fix, test = separate_patches(diff, ("test",))
        assert "Fix code" in fix
        assert test == ""


class TestFindProjectPathsFromDiff:
    def test_finds_app_project_paths(self):
        diff = """diff --git a/App/Apps/W1/Sustainability/app/Code.al b/App/Apps/W1/Sustainability/app/Code.al
--- a/App/Apps/W1/Sustainability/app/Code.al
+++ b/App/Apps/W1/Sustainability/app/Code.al
@@ -1,3 +1,4 @@
+// Fix
 procedure Main()
 begin
 end;
"""
        paths = find_project_paths_from_diff(diff)
        assert len(paths) == 1
        assert "App/Apps/W1/Sustainability/app" in paths

    def test_finds_test_project_paths(self):
        diff = """diff --git a/App/Apps/W1/Sustainability/test/TestCode.al b/App/Apps/W1/Sustainability/test/TestCode.al
--- a/App/Apps/W1/Sustainability/test/TestCode.al
+++ b/App/Apps/W1/Sustainability/test/TestCode.al
@@ -1,3 +1,4 @@
+// Test
 procedure Test()
 begin
 end;
"""
        paths = find_project_paths_from_diff(diff)
        assert len(paths) == 1
        assert "App/Apps/W1/Sustainability/test" in paths

    def test_raises_collection_error_on_empty_diff(self):
        with pytest.raises(CollectionError, match="Patch data is empty or None"):
            find_project_paths_from_diff("")


class TestGHClient:
    def test_get_pr_info_success(self):
        client = GHClient("microsoft/bcapps")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Test PR", "body": "Test body"}',
            )

            result = client.get_pr_info(12345)

            assert result["title"] == "Test PR"
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "gh" in call_args
            assert "pr" in call_args
            assert "view" in call_args
            assert "12345" in call_args

    def test_get_pr_info_failure(self):
        client = GHClient("microsoft/bcapps")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "gh", stderr="Not found")

            with pytest.raises(subprocess.CalledProcessError):
                client.get_pr_info(99999)

    def test_get_pr_diff_success(self):
        client = GHClient("microsoft/bcapps")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="diff --git a/test.al b/test.al\n+test",
            )

            result = client.get_pr_diff(12345)

            assert "diff --git" in result
            call_args = mock_run.call_args[0][0]
            assert "diff" in call_args

    def test_get_file_content_success(self):
        client = GHClient("microsoft/bcapps")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='codeunit 12345 "Test"',
            )

            result = client.get_file_content("test.al", "abc123")

            assert "codeunit 12345" in result
