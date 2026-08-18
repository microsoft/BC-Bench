import logging

from bcbench.collection.patch_utils import split_patch_by_projects

TEST_PROJECTS = ["App\\Apps\\W1\\Shopify\\test"]

RENAME_INTO_TEST_DIFF = """diff --git a/App/Apps/W1/Shopify/app/OrderTest.Codeunit.al b/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al
similarity index 95%
rename from App/Apps/W1/Shopify/app/OrderTest.Codeunit.al
rename to App/Apps/W1/Shopify/test/OrderTest.Codeunit.al
--- a/App/Apps/W1/Shopify/app/OrderTest.Codeunit.al
+++ b/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al
@@ -1,3 +1,4 @@
+    [Test]
"""

RENAME_INTO_APP_DIFF = """diff --git a/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al b/App/Apps/W1/Shopify/app/OrderTest.Codeunit.al
similarity index 95%
rename from App/Apps/W1/Shopify/test/OrderTest.Codeunit.al
rename to App/Apps/W1/Shopify/app/OrderTest.Codeunit.al
--- a/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al
+++ b/App/Apps/W1/Shopify/app/OrderTest.Codeunit.al
@@ -1,4 +1,3 @@
-    [Test]
"""

APP_FILE_DIFF = """diff --git a/App/Apps/W1/Shopify/app/Order.Codeunit.al b/App/Apps/W1/Shopify/app/Order.Codeunit.al
--- a/App/Apps/W1/Shopify/app/Order.Codeunit.al
+++ b/App/Apps/W1/Shopify/app/Order.Codeunit.al
@@ -1,3 +1,3 @@
-    if Quantity < 0 then
+    if Quantity <= 0 then
"""

TEST_FILE_DIFF = """diff --git a/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al b/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al
--- a/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al
+++ b/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al
@@ -1,3 +1,6 @@
+    [Test]
+    procedure TestNegativeQuantity()
"""


def test_app_only_patch_returns_empty_test_half():
    app_patch, test_patch = split_patch_by_projects(APP_FILE_DIFF, TEST_PROJECTS)

    assert app_patch == APP_FILE_DIFF
    assert test_patch == ""


def test_test_only_patch_returns_empty_app_half():
    app_patch, test_patch = split_patch_by_projects(TEST_FILE_DIFF, TEST_PROJECTS)

    assert app_patch == ""
    assert test_patch == TEST_FILE_DIFF


def test_mixed_patch_is_split_by_project():
    app_patch, test_patch = split_patch_by_projects(APP_FILE_DIFF + TEST_FILE_DIFF, TEST_PROJECTS)

    assert app_patch == APP_FILE_DIFF
    assert test_patch == TEST_FILE_DIFF


def test_each_half_keeps_its_diff_git_header():
    app_patch, test_patch = split_patch_by_projects(APP_FILE_DIFF + TEST_FILE_DIFF, TEST_PROJECTS)

    assert app_patch.startswith("diff --git a/App/Apps/W1/Shopify/app/Order.Codeunit.al")
    assert test_patch.startswith("diff --git a/App/Apps/W1/Shopify/test/OrderTest.Codeunit.al")


def test_backslash_project_paths_match_forward_slash_diff_paths():
    _app_patch, test_patch = split_patch_by_projects(TEST_FILE_DIFF, ["App\\Apps\\W1\\Shopify\\test"])

    assert test_patch == TEST_FILE_DIFF


def test_empty_patch_returns_two_empty_strings():
    assert split_patch_by_projects("", TEST_PROJECTS) == ("", "")
    assert split_patch_by_projects("   \n", TEST_PROJECTS) == ("", "")


def test_rename_into_test_project_is_classified_as_test():
    app_patch, test_patch = split_patch_by_projects(RENAME_INTO_TEST_DIFF, TEST_PROJECTS)

    assert app_patch == ""
    assert test_patch == RENAME_INTO_TEST_DIFF


def test_rename_out_of_test_project_is_classified_as_app():
    app_patch, test_patch = split_patch_by_projects(RENAME_INTO_APP_DIFF, TEST_PROJECTS)

    assert app_patch == RENAME_INTO_APP_DIFF
    assert test_patch == ""


def test_content_before_first_header_is_dropped_with_warning(caplog):
    patch = "some preamble noise\n" + APP_FILE_DIFF

    with caplog.at_level(logging.WARNING):
        app_patch, test_patch = split_patch_by_projects(patch, TEST_PROJECTS)

    assert app_patch == APP_FILE_DIFF
    assert test_patch == ""
    assert any("preceding the first" in record.message for record in caplog.records)


def test_patch_with_no_diff_header_is_dropped_with_warning(caplog):
    patch = "not a real diff at all\n"

    with caplog.at_level(logging.WARNING):
        app_patch, test_patch = split_patch_by_projects(patch, TEST_PROJECTS)

    assert app_patch == ""
    assert test_patch == ""
    assert any("No 'diff --git' header" in record.message for record in caplog.records)
