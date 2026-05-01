"""Tests for the bcbench collect gh command."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from bcbench.collection.collect_gh import screen_gh_candidate
from bcbench.collection.gh_client import GHClient
from bcbench.collection.patch_utils import extract_file_paths_from_patch, find_project_paths_from_diff, separate_patches
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
        assert "App\\Apps\\W1\\Sustainability\\app" in paths

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
        assert "App\\Apps\\W1\\Sustainability\\test" in paths

    def test_raises_collection_error_on_empty_diff(self):
        with pytest.raises(CollectionError, match="Patch data is empty or None"):
            find_project_paths_from_diff("")

    def test_finds_layers_project_paths(self):
        diff = """diff --git a/App/Layers/W1/BaseApp/Sales/Reminder/ReminderIssue.Codeunit.al b/App/Layers/W1/BaseApp/Sales/Reminder/ReminderIssue.Codeunit.al
index 9ff59101df2..ff238e73dcf 100644
--- a/App/Layers/W1/BaseApp/Sales/Reminder/ReminderIssue.Codeunit.al
+++ b/App/Layers/W1/BaseApp/Sales/Reminder/ReminderIssue.Codeunit.al
@@ -409,9 +409,6 @@ codeunit 393 "Reminder-Issue"
         if IsHandled then
             exit;

-        if NewDueDate < ReminderEntry2."Due Date" then
-            exit;
-
         ReminderEntry2.Validate("Due Date", NewDueDate);
         ReminderEntry2.Modify();
     end;
diff --git a/App/Layers/W1/Tests/ERM/ERMIssuedReminderAddnlFee.Codeunit.al b/App/Layers/W1/Tests/ERM/ERMIssuedReminderAddnlFee.Codeunit.al
index 71c12b1ce1a..6d8f4aaca9e 100644
--- a/App/Layers/W1/Tests/ERM/ERMIssuedReminderAddnlFee.Codeunit.al
+++ b/App/Layers/W1/Tests/ERM/ERMIssuedReminderAddnlFee.Codeunit.al
@@ -636,6 +636,12 @@ codeunit 134905 "ERM Issued Reminder Addnl Fee"
         ReminderPage.ContactEmail.AssertEquals(EMail);
     end;

+    [Test]
+    procedure VerifyDueDateAfterUpdateDueDateInCustLedgerEntry()
+    begin
+        Initialize();
+    end;
+
     local procedure Initialize()
     var
         LibraryERMCountryData: Codeunit "Library - ERM Country Data";
"""
        paths = find_project_paths_from_diff(diff)
        assert len(paths) == 2
        assert "App\\Layers\\W1\\BaseApp" in paths
        assert "App\\Layers\\W1\\Tests\\ERM" in paths


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


class TestScreenGHCandidate:
    def test_returns_failed_result_when_test_patch_has_no_testable_functions(self):
        diff = """diff --git a/App/Apps/W1/Foo/app/Foo.Codeunit.al b/App/Apps/W1/Foo/app/Foo.Codeunit.al
--- a/App/Apps/W1/Foo/app/Foo.Codeunit.al
+++ b/App/Apps/W1/Foo/app/Foo.Codeunit.al
@@ -1,3 +1,4 @@
+// Fix code
 procedure Main()
 begin
 end;
diff --git a/App/Apps/W1/Foo/test/FooTests.Codeunit.al b/App/Apps/W1/Foo/test/FooTests.Codeunit.al
--- a/App/Apps/W1/Foo/test/FooTests.Codeunit.al
+++ b/App/Apps/W1/Foo/test/FooTests.Codeunit.al
@@ -1,3 +1,4 @@
+// Not a test procedure
 procedure Helper()
 begin
 end;
"""

        with patch("bcbench.collection.collect_gh.GHClient") as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.get_pr_info.return_value = {"mergeCommit": {"oid": "abc123"}}
            mock_client.get_pr_diff.return_value = diff
            mock_client.get_file_content.return_value = 'codeunit 12345 "Foo Tests"'

            result = screen_gh_candidate(12345)

            assert not result.passed
            assert result.reason == "No testable functions found in test patch"


class TestExtractFilePathsFromPatch:
    def test_extracts_single_file_path(self):
        patch = """diff --git a/App/Code.al b/App/Code.al
--- a/App/Code.al
+++ b/App/Code.al
@@ -1,3 +1,4 @@
+// Fix code
 procedure MainCode()
 begin
 end;
"""
        result = extract_file_paths_from_patch(patch)
        assert result == ["App/Code.al"]

    def test_extracts_multiple_file_paths(self):
        patch = """diff --git a/App/Apps/W1/Sustainability/app/Code.al b/App/Apps/W1/Sustainability/app/Code.al
--- a/App/Apps/W1/Sustainability/app/Code.al
+++ b/App/Apps/W1/Sustainability/app/Code.al
@@ -1,3 +1,4 @@
+// Fix
 procedure Main()
 begin
 end;
diff --git a/App/Apps/W1/Sustainability/test/TestCode.al b/App/Apps/W1/Sustainability/test/TestCode.al
--- a/App/Apps/W1/Sustainability/test/TestCode.al
+++ b/App/Apps/W1/Sustainability/test/TestCode.al
@@ -1,3 +1,4 @@
+// Test
 procedure Test()
 begin
 end;
"""
        result = extract_file_paths_from_patch(patch)
        assert len(result) == 2
        assert "App/Apps/W1/Sustainability/app/Code.al" in result
        assert "App/Apps/W1/Sustainability/test/TestCode.al" in result

    def test_returns_empty_list_for_empty_patch(self):
        result = extract_file_paths_from_patch("")
        assert result == []

    def test_extracts_paths_from_layers_structure(self):
        patch = """diff --git a/App/Layers/W1/BaseApp/Sales/ReminderIssue.Codeunit.al b/App/Layers/W1/BaseApp/Sales/ReminderIssue.Codeunit.al
--- a/App/Layers/W1/BaseApp/Sales/ReminderIssue.Codeunit.al
+++ b/App/Layers/W1/BaseApp/Sales/ReminderIssue.Codeunit.al
@@ -1,3 +1,4 @@
+// Fix
 procedure Main()
 begin
 end;
diff --git a/App/Layers/W1/Tests/ERM/ERMIssuedReminderAddnlFee.Codeunit.al b/App/Layers/W1/Tests/ERM/ERMIssuedReminderAddnlFee.Codeunit.al
--- a/App/Layers/W1/Tests/ERM/ERMIssuedReminderAddnlFee.Codeunit.al
+++ b/App/Layers/W1/Tests/ERM/ERMIssuedReminderAddnlFee.Codeunit.al
@@ -1,3 +1,4 @@
+// Test
 procedure Test()
 begin
 end;
"""
        result = extract_file_paths_from_patch(patch)
        assert len(result) == 2
        assert "App/Layers/W1/BaseApp/Sales/ReminderIssue.Codeunit.al" in result
        assert "App/Layers/W1/Tests/ERM/ERMIssuedReminderAddnlFee.Codeunit.al" in result
