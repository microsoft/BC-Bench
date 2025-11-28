import pytest

from bcbench.exceptions import NoTestsExtractedError
from bcbench.operations.test_operations import extract_tests_from_patch


def test_single_test_procedure():
    file_path = "App/Apps/W1/Sustainability/test/src/SustCertificateTest.Codeunit.al"
    file_contents = {file_path: 'codeunit 148187 "Sust. Certificate Test" { }'}

    patch = """
diff --git a/App/Apps/W1/Sustainability/test/src/SustCertificateTest.Codeunit.al b/App/Apps/W1/Sustainability/test/src/SustCertificateTest.Codeunit.al
index ff9b7640fa2..07bfdfa1233 100644
--- a/App/Apps/W1/Sustainability/test/src/SustCertificateTest.Codeunit.al
+++ b/App/Apps/W1/Sustainability/test/src/SustCertificateTest.Codeunit.al
@@ -5123,6 +5123,47 @@ codeunit 148187 "Sust. Certificate Test"
         // [THEN] Confirmation Box should not pop up as there is no confirm Handler.
     end;

+    [Test]
+    [HandlerFunctions('ConfirmHandlerYes')]
+    procedure VerifyEmissionFieldsMustBeEnabledWhenEnableValueChainTrackingIsEnabled()
+    var
+        SustainabilitySetup: Record "Sustainability Setup";
+    begin
+        // [SCENARIO 569462] Verify fields must be enabled
+    end;
    """

    result = extract_tests_from_patch(patch, file_contents)

    assert len(result) == 1
    assert result[0].codeunitID == 148187
    assert result[0].functionName == {"VerifyEmissionFieldsMustBeEnabledWhenEnableValueChainTrackingIsEnabled"}


def test_multiple_tests_same_codeunit():
    file_path = "App/Layers/W1/Tests/SCM/SCMBugfixes.Codeunit.al"
    file_contents = {file_path: 'codeunit 137045 "SCM Bugfixes" { }'}

    patch = """
diff --git a/App/Layers/W1/Tests/SCM/SCMBugfixes.Codeunit.al b/App/Layers/W1/Tests/SCM/SCMBugfixes.Codeunit.al
index abc..def 100644
--- a/App/Layers/W1/Tests/SCM/SCMBugfixes.Codeunit.al
+++ b/App/Layers/W1/Tests/SCM/SCMBugfixes.Codeunit.al
@@ -10,6 +10,20 @@ codeunit 137045 "SCM Bugfixes"
{
+    [Test]
+    procedure TestOne()
+    begin
+    end;

+    [Test]
+    [HandlerFunctions('MessageHandlerOrderTracking')]
+    procedure TestTwo()
+    begin
+    end;
}
    """

    result = extract_tests_from_patch(patch, file_contents)

    assert len(result) == 1
    assert result[0].codeunitID == 137045
    assert len(result[0].functionName) == 2
    assert "TestOne" in result[0].functionName
    assert "TestTwo" in result[0].functionName


def test_test_with_handler_functions():
    file_path = "App/ShopifyTest.Codeunit.al"
    file_contents = {file_path: 'codeunit 139648 "Shpfy Suggest Payment Test" { }'}

    patch = """
diff --git a/App/ShopifyTest.Codeunit.al b/App/ShopifyTest.Codeunit.al
index abc..def 100644
--- a/App/ShopifyTest.Codeunit.al
+++ b/App/ShopifyTest.Codeunit.al
@@ -5,6 +5,15 @@ codeunit 139648 "Shpfy Suggest Payment Test"
{
+    [Test]
+    [HandlerFunctions('SuggestShopifyPaymentsRequestPageHandler')]
+    procedure UnitTestSuggestShopifyPaymentsFailedTransaction()
+    var
+        Item: Record Item;
+    begin
+        // Test code
+    end;
}
    """

    result = extract_tests_from_patch(patch, file_contents)

    assert len(result) == 1
    assert result[0].codeunitID == 139648
    assert result[0].functionName == {"UnitTestSuggestShopifyPaymentsFailedTransaction"}


def test_no_tests_in_patch():
    patch = """
diff --git a/App/Apps/W1/Sustainability/app/src/Setup/SustainabilitySetup.Table.al
table 6217 "Sustainability Setup"
{
    procedure SomeNonTestProcedure()
    begin
    end;
}
    """

    with pytest.raises(NoTestsExtractedError):
        extract_tests_from_patch(patch, {})


def test_test_attribute_with_comment():
    file_path = "App/TestCodeunit.Codeunit.al"
    file_contents = {file_path: 'codeunit 148187 "Test Codeunit" { }'}

    patch = """
diff --git a/App/TestCodeunit.Codeunit.al b/App/TestCodeunit.Codeunit.al
index abc..def 100644
--- a/App/TestCodeunit.Codeunit.al
+++ b/App/TestCodeunit.Codeunit.al
@@ -5,6 +5,12 @@ codeunit 148187 "Test Codeunit"
{
+    [Test]
+    // Comment here
+
+    procedure MyTestFunction()
+    begin
+    end;
}
    """

    result = extract_tests_from_patch(patch, file_contents)

    assert len(result) == 1
    assert result[0].codeunitID == 148187
    assert result[0].functionName == {"MyTestFunction"}


def test_procedure_without_test_attribute():
    file_path = "App/TestCodeunit2.Codeunit.al"
    file_contents = {file_path: 'codeunit 148187 "Test Codeunit" { }'}

    patch = """
diff --git a/App/TestCodeunit2.Codeunit.al b/App/TestCodeunit2.Codeunit.al
index abc..def 100644
--- a/App/TestCodeunit2.Codeunit.al
+++ b/App/TestCodeunit2.Codeunit.al
@@ -5,6 +5,16 @@ codeunit 148187 "Test Codeunit"
{
+    procedure NotATestFunction()
+    begin
+    end;

+    [Test]
+    procedure ActualTestFunction()
+    begin
+    end;
}
    """

    result = extract_tests_from_patch(patch, file_contents)

    assert len(result) == 1
    assert result[0].codeunitID == 148187
    assert result[0].functionName == {"ActualTestFunction"}


def test_complex_real_world_patch():
    file_path = "App/Layers/W1/Tests/SCM/SCMBugfixes.Codeunit.al"
    file_contents = {file_path: 'codeunit 137045 "SCM Bugfixes" { }'}

    patch = """
diff --git a/App/Layers/W1/Tests/SCM/SCMBugfixes.Codeunit.al b/App/Layers/W1/Tests/SCM/SCMBugfixes.Codeunit.al
index bfcb627e6e5..f8db5ec3cf2 100644
--- a/App/Layers/W1/Tests/SCM/SCMBugfixes.Codeunit.al
+++ b/App/Layers/W1/Tests/SCM/SCMBugfixes.Codeunit.al
@@ -1217,6 +1217,76 @@ codeunit 137045 "SCM Bugfixes"
         AssertReservationEntryCountForSales(SalesHeader, 3);
     end;

+    [Test]
+    [HandlerFunctions('MessageHandlerOrderTracking,ItemTrackingLinesPageHandler')]
+    procedure CheckTrackingReservationEntriesUpdatedWheLotNoAllocated()
+    var
+        Item: Record Item;
+        Location: Record Location;
+    begin
+        // [SCENARIO 580079] Test scenario
+        Initialize();
+
+        // Test implementation
+    end;
+
     local procedure Initialize()
    """

    result = extract_tests_from_patch(patch, file_contents)

    assert len(result) == 1
    assert result[0].codeunitID == 137045
    assert result[0].functionName == {"CheckTrackingReservationEntriesUpdatedWheLotNoAllocated"}


def test_indented_test_procedure():
    file_path = "App/IndentTest.Codeunit.al"
    file_contents = {file_path: 'codeunit 137045 "Test Codeunit" { }'}

    patch = """
diff --git a/App/IndentTest.Codeunit.al b/App/IndentTest.Codeunit.al
index abc..def 100644
--- a/App/IndentTest.Codeunit.al
+++ b/App/IndentTest.Codeunit.al
@@ -5,6 +5,14 @@ codeunit 137045 "Test Codeunit"
{
+    [Test]
+    procedure TestWithIndentation()
+    var
+        Item: Record Item;
+    begin
+        // Test code
+    end;
}
    """

    result = extract_tests_from_patch(patch, file_contents)

    assert len(result) == 1
    assert result[0].codeunitID == 137045
    assert result[0].functionName == {"TestWithIndentation"}


def test_empty_patch():
    patch = ""

    with pytest.raises(NoTestsExtractedError):
        extract_tests_from_patch(patch, {})


def test_patch_with_no_codeunit_id():
    patch = """
+    [Test]
+    procedure TestWithoutCodeunit()
+    begin
+    end;
    """

    with pytest.raises(NoTestsExtractedError):
        extract_tests_from_patch(patch, {})


def test_context_lines_without_plus_marker():
    file_path = "App/ContextTest.Codeunit.al"
    file_contents = {file_path: 'codeunit 139648 "Shpfy Suggest Payment Test" { }'}

    patch = """
diff --git a/App/ContextTest.Codeunit.al b/App/ContextTest.Codeunit.al
index abc..def 100644
--- a/App/ContextTest.Codeunit.al
+++ b/App/ContextTest.Codeunit.al
@@ -5,6 +5,11 @@ codeunit 139648 "Shpfy Suggest Payment Test"
{
+    [Test]
+    procedure NewTestFunction()
+    begin
+    end;

    [Test]
    procedure ExistingTestFunction()
    begin
    end;
}
    """

    result = extract_tests_from_patch(patch, file_contents)

    # Only the new test should be extracted
    assert len(result) == 1
    assert result[0].codeunitID == 139648
    assert result[0].functionName == {"NewTestFunction"}
    assert "ExistingTestFunction" not in result[0].functionName


def test_non_codeunit_files_are_skipped():
    file_contents = {
        "App/Test.Codeunit.al": 'codeunit 148100 "Test Codeunit" { }',
        "App/NoSeriesTest.PermissionSet.al": 'permissionset 139480 "NoSeriesTest" { }',
    }

    patch = """
diff --git a/App/NoSeriesTest.PermissionSet.al b/App/NoSeriesTest.PermissionSet.al
index abc..def 100644
--- a/App/NoSeriesTest.PermissionSet.al
+++ b/App/NoSeriesTest.PermissionSet.al
@@ -1,5 +1,10 @@ permissionset 139480 "NoSeriesTest"
{
+    Permissions = tabledata "No. Series" = RIMD;
}
diff --git a/App/Test.Codeunit.al b/App/Test.Codeunit.al
index abc..def 100644
--- a/App/Test.Codeunit.al
+++ b/App/Test.Codeunit.al
@@ -5,6 +5,11 @@ codeunit 148100 "Test Codeunit"
{
+    [Test]
+    procedure ActualTest()
+    begin
+    end;
}
    """

    result = extract_tests_from_patch(patch, file_contents)

    assert len(result) == 1
    assert result[0].codeunitID == 148100
    assert result[0].functionName == {"ActualTest"}


def test_multiple_files_touched():
    file_contents = {
        "App/Test1.Codeunit.al": 'codeunit 148100 "Test Codeunit One" { }',
        "App/Test2.Codeunit.al": 'codeunit 148200 "Test Codeunit Two" { }',
    }

    patch = """
diff --git a/App/Test1.Codeunit.al b/App/Test1.Codeunit.al
index abc123..def456 100644
--- a/App/Test1.Codeunit.al
+++ b/App/Test1.Codeunit.al
@@ -10,6 +10,15 @@ codeunit 148100 "Test Codeunit One"
     end;

+    [Test]
+    procedure FirstTestInFile1()
+    begin
+        // Test code
+    end;
+
+    [Test]
+    procedure SecondTestInFile1()
+    begin
+        // Test code
+    end;

     local procedure Helper()
diff --git a/App/Test2.Codeunit.al b/App/Test2.Codeunit.al
index ghi789..jkl012 100644
--- a/App/Test2.Codeunit.al
+++ b/App/Test2.Codeunit.al
@@ -5,6 +5,11 @@ codeunit 148200 "Test Codeunit Two"
     end;

+    [Test]
+    procedure TestInFile2()
+    begin
+        // Test code
+    end;

     local procedure Setup()
    """

    result = extract_tests_from_patch(patch, file_contents)

    # Should have 2 entries, one for each codeunit
    assert len(result) == 2

    # Find entries for each codeunit
    entry1 = next((e for e in result if e.codeunitID == 148100), None)
    entry2 = next((e for e in result if e.codeunitID == 148200), None)

    assert entry1 is not None
    assert len(entry1.functionName) == 2
    assert "FirstTestInFile1" in entry1.functionName
    assert "SecondTestInFile1" in entry1.functionName

    assert entry2 is not None
    assert len(entry2.functionName) == 1
    assert "TestInFile2" in entry2.functionName
